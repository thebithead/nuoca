import json
import logging
import numpy
import requests
import threading
import time

from collections import defaultdict
from nuoca_plugin import NuocaMPInputPlugin
from nuoca_util import nuoca_log, nuoca_gettimestamp

# mpNuoMonitor plugin
#
# Example mpNuoMonitor plugin configuration:
#
# - mpNuoMonitor:
#    description : Collection from internal nuomonitor tool
#    broker: 172.19.0.16
#    nuomonitor_host: localhost
#    nuomonitor_port: 8028
#    nuomonitor_interval: 10


class MPNuoMonitor(NuocaMPInputPlugin):
  def __init__(self, parent_pipe):
    super(MPNuoMonitor, self).__init__(parent_pipe, 'NuoMonitor')
    self._config = None
    self._broker = None
    self._enabled = False
    self._nuomonitor_host = None
    self._nuomonitor_port = None
    self._nuomonitor_interval = None
    self._nuomonitor_url = None
    self._thread = None
    self._nuomonitor_collect_queue = []

  def _collection_cycle(self, next_interval_time):
    rval = None
    try:
      response = requests.get(self._nuomonitor_url)
      if response.status_code != 200:
        nuoca_log(logging.ERROR,
                  "NuoMonitor plugin got non-200 "
                  "response from nuomonitor: %s" % str(response))
        return rval
      rval = json.loads(response.content)
      # print(rval)
    except Exception as e:
      nuoca_log(logging.ERROR, str(e))
    return rval

  def _collection_thread(self):
    # Find the start of the next time interval
    current_timestamp = nuoca_gettimestamp()
    next_interval_time = current_timestamp + self._nuomonitor_interval

    # Collection Interval Loop
    loop_count = 0
    while self._enabled:
      try:
        loop_count += 1
        current_timestamp = nuoca_gettimestamp()
        waittime = next_interval_time - current_timestamp
        if waittime > 0:
          time.sleep(waittime)
        next_interval_time += self._nuomonitor_interval
        content = self._collection_cycle(next_interval_time)
        for ci in content:
          self._nuomonitor_collect_queue.append(ci)
      except Exception as e:
        nuoca_log(logging.ERROR, str(e))

  def startup(self, config=None):
    try:
      self._config = config

      # Validate the configuration.
      if not config:
        nuoca_log(logging.ERROR, "NuoMonitor plugin missing config")
        return False
      required_config_items = ['broker', 'nuomonitor_host',
                               'nuomonitor_port', 'nuomonitor_interval']
      for config_item in required_config_items:
        if config_item not in config:
          nuoca_log(logging.ERROR,
                    "NuoMonitor plugin '%s' missing from config" %
                    config_item)
          return False

      nuoca_log(logging.INFO, "NuoMonitor plugin config: %s" %
                str(self._config))

      self._broker = config['broker']
      self._nuomonitor_host = config['nuomonitor_host']
      self._nuomonitor_port = config['nuomonitor_port']
      self._nuomonitor_interval = config['nuomonitor_interval']
      self._nuomonitor_url = "http://%s:%s/api/v1/metrics/latest" % \
                             (self._nuomonitor_host,
                              self._nuomonitor_port)
      self._enabled = True
      self._thread = threading.Thread(target=self._collection_thread)
      self._thread.daemon = True
      self._thread.start()
      return True
    except Exception as e:
      nuoca_log(logging.ERROR, str(e))
      return False

  def shutdown(self):
    self.enabled = False
    pass

  def collect(self, collection_interval):
    rval = None
    try:
      if collection_interval < self._nuomonitor_interval:
        nuoca_log(logging.ERROR,
                  "nuoca collection interval %s is smaller "
                  "than the NuoMonitor plugin interval %s" % (
                      collection_interval,
                      self._nuomonitor_interval
                  ))
        return None
      nuoca_log(logging.DEBUG, "Called collect() in NuoMonitor Plugin process")
      rval = super(MPNuoMonitor, self).collect(collection_interval)
      collection_count = len(self._nuomonitor_collect_queue)
      if not collection_count:
        return rval
      intermediate = defaultdict(list)
      for subdict in self._nuomonitor_collect_queue:
        for key, value in subdict.items():
          intermediate[key].append(value)
      for ci in intermediate:
        if isinstance(intermediate[ci][0], (int)):
          rval[ci] = int(numpy.mean(intermediate[ci]))
        elif isinstance(intermediate[ci][0], (float)):
          rval[ci] = numpy.mean(intermediate[ci])
        else:
          rval[ci] = intermediate[ci][-1]
      print(rval)
    except Exception as e:
      nuoca_log(logging.ERROR, str(e))
    return rval