import click
import json
import traceback
from nuoca_util import *
from yapsy.MultiprocessPluginManager import MultiprocessPluginManager
from nuoca_plugin import NuocaMPInputPlugin, NuocaMPOutputPlugin, NuocaMPTransformPlugin
from nuoca_config import NuocaConfig


class NuoCA(object):
  """
  NuoDB Collection Agent
  """
  def __init__(self, config_file=None, collection_interval=30,
               plugin_dir=None, starttime=None, verbose=False):
    """
    :param config_file: Path to NuoCA configuration file.
    :type config_file: ``str``

    :param collection_interval: Collection Interval in seconds
    :type collection_interval: ``int``

    :param plugin_dir: Path to NuoCA Plugin Directory
    :type plugin_dir: ``str``

    :param starttime: Epoch timestamp of start time of the first collection.
    :type starttime: ``int``

    :param verbose: Flag to indicate printing of verbose messages to stdout.
    :type verbose: ``bool``
    """
    self._config = NuocaConfig(config_file)
    nuoca_set_log_level(logging.INFO)
    nuoca_log(logging.INFO, "nuoca server init.")
    self._collection_interval = collection_interval
    self._starttime = starttime
    self._plugin_topdir = plugin_dir
    self._enabled = True
    self._verbose = verbose
    if not self._plugin_topdir:
      self._plugin_topdir = os.path.join(get_nuoca_topdir(),
                                         "plugins")
    nuoca_log(logging.INFO, "plugin dir: %s" % self._plugin_topdir)
    input_plugin_dir = os.path.join(self._plugin_topdir, "input")
    output_plugin_dir = os.path.join(self._plugin_topdir, "output")
    transform_plugin_dir = os.path.join(self._plugin_topdir, "transform")
    self._plugin_directories = [input_plugin_dir,
                                output_plugin_dir,
                                transform_plugin_dir]


  def _collection_cycle(self, starttime):
    """
    _collection_cycle is called at the beginning of each Collection
    Interval.
    """
    nuoca_log(logging.INFO, "Starting collection interval: %s" % starttime)
    collected_inputs = self._collect_inputs()
    collected_inputs['CollectionInterval'] = self._collection_interval
    collected_inputs['timestamp'] = starttime + self._collection_interval
    # TODO Transformations
    self._store_outputs(collected_inputs)

  def _get_activated_input_plugins(self):
    """
    Get a list of "activated" plugins
    """
    input_list = self.manager.getPluginsOfCategory('Input')
    activated_list = [x for x in input_list if x.is_activated]
    return activated_list

  def _collect_inputs(self):
    """
    Collect time-series data from each activated plugin.
    :return: ``dict`` of time-series data
    """
    # TODO - Use Threads so that we can do concurrent collection.
    plugin_msg = "Collect"
    rval = {}
    resp_values = None
    activated_plugins = self._get_activated_input_plugins()

    for a_plugin in activated_plugins:
      # noinspection PyBroadException
      try:
        a_plugin.plugin_object.child_pipe.send(plugin_msg)
      except Exception as e:
        nuoca_log(logging.ERROR,
                  "Unable to send 'Collect' message to plugin: %s"
                  % a_plugin.name)

    for a_plugin in activated_plugins:
      plugin_resp_msg = None
      resp_values = None
      plugin_obj = a_plugin.plugin_object
      # noinspection PyBroadException
      try:
        if plugin_obj.child_pipe.poll(self._config.PLUGIN_PIPE_TIMEOUT):
          plugin_resp_msg = plugin_obj.child_pipe.recv()
          if self._verbose:
            print("%s:%s" % (a_plugin.name, plugin_resp_msg))
          resp_values = json.loads(plugin_resp_msg)
        else:
          nuoca_log(logging.ERROR,
                    "Timeout collecting response values from plugin: %s"
                    % a_plugin.name)
          continue

      except Exception as e:
        nuoca_log(logging.ERROR,
                  "Unable to collect response from plugin: %s"
                  % a_plugin.name)
        continue

      # noinspection PyBroadException
      try:
        if not resp_values:
          nuoca_log(logging.ERROR,
                    "Unable to collect response values from plugin: %s"
                    % a_plugin.name)
          continue
        if resp_values['StatusCode'] != 0:
          nuoca_log(logging.ERROR,
                    "Error collecting values from plugin: %s"
                    % a_plugin.name)
          continue
        if 'Collected_Values' not in resp_values:
          nuoca_log(logging.ERROR,
                    "'Collected_Values' missing in response from plugin: %s"
                    % a_plugin.name)
          continue
        rval.update(resp_values['Collected_Values'])
      except Exception as e:
        nuoca_log(logging.ERROR,
                  "Unknown error attempting to collect"
                  " response from plugin: %s"
                  % a_plugin.name)

    return rval

  def _store_outputs(self, collected_inputs):
    # TODO Implement after output plugins are implemented.
    pass


  def _create_plugin_manager(self):
    self.manager = MultiprocessPluginManager(
        directories_list=self._plugin_directories,
        plugin_info_ext="multiprocess-plugin")
    self.manager.setCategoriesFilter({
        "Input": NuocaMPInputPlugin,
        "Ouput": NuocaMPOutputPlugin,
        "Transform": NuocaMPTransformPlugin
    })

  def _load_plugins(self):
    self.manager.collectPlugins()
    for input_plugin in self._config.INPUT_PLUGINS:
      self.manager.activatePluginByName(input_plugin, 'Input')

  def start(self):
    """
    Startup NuoCA
    """
    self._create_plugin_manager()
    self._load_plugins()

    # Find the start of the next time interval
    current_timestamp = nuoca_gettimestamp()
    next_interval_starttime = current_timestamp
    if self._starttime:
      if current_timestamp >= self._starttime:
        msg = "starttime must be in the future."
        nuoca_log(logging.ERROR, msg)
        raise AttributeError(msg)
      next_interval_starttime = self._starttime

    # Collection Interval Loop
    while self._enabled:
      current_timestamp = nuoca_gettimestamp()
      waittime = next_interval_starttime - current_timestamp
      if waittime > 0:
        time.sleep(waittime)
      next_interval_starttime += self._collection_interval
      self._collection_cycle(next_interval_starttime)

  # noinspection PyMethodMayBeStatic
  def shutdown(self):
    """
    Shutdown NuoCA
    """
    nuoca_log(logging.INFO, "nuoca server shutdown")
    nuoca_logging_shutdown()


@click.command()
@click.option('--collection-interval', default=30,
              help='Optional collection interval in seconds')
@click.option('--config-file', default=None,
              help='NuoCA configuration file')
@click.option('--plugin-dir', default=None,
              help='Optional path to plugin directory')
@click.option('--starttime', default=None,
              help='Optional start time in Epoch seconds '
                   'for first collection interval')
@click.option('--verbose', is_flag=True, default=False,
              help='Run with verbose messages written to stdout')
def nuoca(config_file, collection_interval, plugin_dir, starttime, verbose):
  nuoca_obj = None
  try:
    nuoca_obj = NuoCA(config_file, collection_interval,
                      plugin_dir, starttime, verbose)
    nuoca_obj.start()
  except AttributeError as e:
    msg = str(e)
    nuoca_log(logging.ERROR, msg)
    print(msg)
  except Exception as e:
    msg = "Unhandled exception: %s" % e
    nuoca_log(logging.ERROR, msg)
    print(msg)
    stacktrace = traceback.format_exc()
    print(stacktrace)
  finally:
    if nuoca_obj:
      nuoca_obj.shutdown()
  print("Done.")


if __name__ == "__main__":
  nuoca()

