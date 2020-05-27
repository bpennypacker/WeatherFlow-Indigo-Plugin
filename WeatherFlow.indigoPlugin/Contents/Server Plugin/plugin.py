#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.
# import indigo

import os
import sys
import time
import json
import requests
import traceback
import Queue
import threading
import websocket
import socket
import datetime
import webbrowser

api_key = "20c70eae-e62f-4d3b-b3a4-8586e90f3ac8"

urls = {
  'station': "https://swd.weatherflow.com/swd/rest/stations/{}?api_key={}",
  'websocket': "wss://ws.weatherflow.com/swd/data?api_key={}"
}

MSG_WEBSOCKET=1
MSG_UDP=2
MSG_DEBUG=3
MSG_ERROR=4

device_suffix = {
    MSG_WEBSOCKET : "WS",
    MSG_UDP : "UDP"
}

obs_sky_map = {
    'timestamp' :                     0,
    'illuminance' :                   1,
    'uv':                             2, 
    'rain_accumulated':               3,
    'wind_lull':                      4,
    'wind_average':                   5,
    'wind_gust':                      6,
    'wind_direction':                 7,
    'battery':                        8,
    'report_interval':                9,
    'solar_radiation':               10,
    'daily_rain_accumulation':       11,
    'wind_sample_interval':          13,
    'rain_accumulated_final':        14,
    'daily_rain_accumulation_final': 15
} 

obs_air_map = {
    'timestamp' :                        0,
    'pressure':                          1,
    'temperature':                       2,
    'relative_humidity':                 3,
    'lightning_strike_count':            4,
    'lightning_strike_average_distance': 5,
    'battery':                           6,
    'report_interval':                   7
}

obs_tempest_map = {
    'timestamp' :                         0,
    'wind_lull':                          1,
    'wind_average':                       2,
    'wind_gust':                          3,
    'wind_direction':                     4,
    'wind_sample_interval':               5,
    'pressure':                           6,
    'temperature':                        7,
    'relative_humidity':                  8,
    'illuminance' :                       9,
    'uv':                                10,
    'solar_radiation':                   11,
    'precipitation':                     12,
    'lightning_strike_average_distance': 14,
    'lightning_strike_count':            15,
    'battery':                           16,
    'report_interval':                   17,
    'rain_accumulated_final':            18,
    'daily_rain_accumulation_final':     19,
}

rapid_wind_map = {
    'timestamp':                      0,
    'wind_speed':                     1,
    'wind_direction':                 2
}

evt_strike_map = {
    'last_strike' :                      0,
    'strike_distance' :                  1,
    'strike_energy' :                    2
}

# Decimal precision of various fields in above maps
obs_precision = {
    'pressure':                           2,
    'temperature':                        1,
    'battery':                            2,
    'rain_accumulated':                   1,
    'wind_lull':                          1,
    'wind_average':                       1,
    'wind_gust':                          1,
    'daily_rain_accumulation':            2,
    'rain_accumulated_final':             1,
    'daily_rain_accumulation_final':      1
}

precip_type = ['none', 'rain', 'hail', 'rhmix']

################################################################################
class WeatherFlowUDPWorker(threading.Thread):
    def __init__(self, msg_queue):
        threading.Thread.__init__(self)
        self.ws = None
        self.queue = msg_queue
        self.devices=[]
        self.socket = None
        self.Listening = True
        self.serial_numbers = []

    ########################################
    def _debug(self, msg):
        if self.queue != None:
            self.queue.put((MSG_DEBUG, None, msg))

    ########################################
    def _error(self, msg):
        if self.queue != None:
            self.queue.put((MSG_ERROR, None, msg))

    ########################################
    def shutdown(self):
        self.Listening = False

    ########################################
    def get_serial_numbers(self):
        return self.serial_numbers

    ########################################
    def run(self):
        self._debug("Starting UDP listener loop on port 50222")
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Allow sharing of the port
            self.socket.bind(('', 50222))
        except Exception as e:
            self._error(traceback.format_exception(*sys.exc_info()))
            self._debug(str(e))
            self.socket = None

        while self.Listening:
            if self.socket == None:
                time.sleep(1)
            else:
                try:
                    buf = self.socket.recvfrom(2048)
                    msg = buf[0]
                    j = json.loads(msg)
                    if 'serial_number' in j and j['serial_number'] not in self.serial_numbers:
                        self.serial_numbers.append(j['serial_number'])
                        self._debug("added device serial number {}".format(j['serial_number']))

                    if 'type' in j and j['type'] in [ 'obs_air', 'obs_sky', 'rapid_wind', 'obs_st' ]:
                        self.queue.put((MSG_UDP, j['serial_number'], msg))
                        self._debug(json.dumps(j, sort_keys=True, indent=4, separators=(',', ': ')))

                except Exception as e:
                    self._error(traceback.format_exception(*sys.exc_info()))
                    self._debug(str(e))

################################################################################
# We spin up a single thread of this class when Websocket devices are enabled
# It receives messages from WeatherFlow and pushes messages we're interested in
# onto the msg_queue.
class WeatherFlowWebsocketWorker(threading.Thread):
    def __init__(self, api_key, msg_queue):
        threading.Thread.__init__(self)
        self.api_key = api_key
        self.ws = None
        self.queue = msg_queue
        self.devices=[]
        self.ready = False
        self.wsRunning = True

    ########################################
    def _debug(self, msg):
        if self.queue != None:
            self.queue.put((MSG_DEBUG, None, msg))

    ########################################
    def _error(self, msg):
        if self.queue != None:
            self.queue.put((MSG_ERROR, None, msg))

    ########################################
    def shutdown(self):
        if self.ws != None:
            for x in self.devices:
                (d, n) = x.split('-')
                payload = { "type": "listen_stop", "device_id": d, "id": "indigo-{}".format(d) }
                p = json.dumps(payload)
                self._debug(p)
                self.ws.send(p)

            self.wsRunning = False
            self.ws.keep_running = False

    ########################################
    def _swws_on_message(self, WS, message):
        j = json.loads(message)
        if self.queue != None:
            self._debug(json.dumps(j, sort_keys=True, indent=4, separators=(',', ': ')))
            self.queue.put((MSG_WEBSOCKET, j['device_id'], message))

    ########################################
    def _swws_on_error(self, WS, error):
        self._debug("Websocket error: {}".format(error))

    ########################################
    def _swws_on_open(self, WS):
        self._debug("Websocket on_open")
        self.ready = True

        # If self.devices has entries in it then those are devices we were
        # previously being listened to, so start listening again...
        for x in self.devices:
            (d, t) = x.split('-')
            if t in [ 'SmartWeatherAirWS', 'SmartWeatherSkyWS', 'SmartWeatherTempestWS' ]:
                payload = { "type": "listen_start", "device_id": d, "id": "indigo-{}".format(d) }
            elif devtype == 'SmartWeatherRapidWindWS':
                payload = { "type": "listen_rapid_start", "device_id": d, "id": "indigo-{}".format(d) }
            else:
                self._debug("Error: Unrecognized type '{}'".format(devtype))
                continue

            p = json.dumps(payload)
            self._debug(p)
            try:
                 self.ws.send(p)
            except Exception as e:
                self._error(traceback.format_exception(*sys.exc_info()))

    ########################################
    def _swws_on_close(self, WS):
        self._debug("Websocket on_close")
        WS.keep_running = False
        self.ws = None
        self.ready = False

    ########################################
    def run(self):

        while self.wsRunning:
            try:
                self.ws = websocket.WebSocketApp("wss://ws.weatherflow.com/swd/data?api_key={}".format(self.api_key),
                              on_message = lambda ws,msg: self._swws_on_message(ws, msg),
                              on_error   = lambda ws,msg: self._swws_on_error(ws, msg),
                              on_open    = lambda ws:     self._swws_on_open(ws),
                              on_close   = lambda ws:     self._swws_on_close(ws))

                self.ws.run_forever()
            except Exception as e:
                self.ws = None
                self._error(traceback.format_exception(*sys.exc_info()))
                self._debug(str(e))
                time.sleep(5)

    ########################################
    def add_device(self, dev, devtype):
        retry = 10
        while not self.ready:
            time.sleep(1)
            retry = retry - 1
            if retry <= 0:
                self._debug("Error adding device. websocket not ready.")
                return
        
        if devtype in [ 'SmartWeatherAirWS', 'SmartWeatherSkyWS', 'SmartWeatherTempestWS' ]:
            payload = { "type": "listen_start", "device_id": dev, "id": "indigo-{}".format(dev) }
        elif devtype == 'SmartWeatherRapidWindWS':
            payload = { "type": "listen_rapid_start", "device_id": dev, "id": "indigo-{}".format(dev) }
        else:
            self._debug("Error: Unrecognized type '{}'".format(devtype))
            return
     
        p = json.dumps(payload)
        self._debug(p)
        try:
            self.ws.send(p)
        except Exception as e:
            self._error(traceback.format_exception(*sys.exc_info()))

        dd = "{}-{}".format(dev, devtype)
        self._debug("adding device {}".format(dd))
        self.devices.append(dd)

    ########################################
    def remove_device(self, dev, devtype):
        retry = 10
        while not self.ready:
            time.sleep(1)
            retry = retry - 1
            if retry <= 0:
                self._debug("Error adding device. websocket not ready.")
                return

        if devtype in [ 'SmartWeatherAirWS', 'SmartWeatherSkyWS', 'SmartWeatherTempestWS' ]:
            payload = { "type": "listen_stop", "device_id": dev, "id": "indigo-{}".format(dev) }
        elif devtype == 'SmartWeatherRapidWindWS':
            payload = { "type": "listen_rapid_stop", "device_id": dev, "id": "indigo-{}".format(dev) }
        else:
            self._debug("Error: Unrecognized type '{}'".format(devtype))
            return

        p = json.dumps(payload)
        self._debug(p)
        try:
            self.ws.send(p)
        except Exception as e:
            self._error(traceback.format_exception(*sys.exc_info()))

        dd = "{}-{}".format(dev, devtype)
        self._debug("removing device {}".format(dd))
        self.devices.remove(dd)

################################################################################
def isInt(i):
    try:
        int(i)
        return True
    except:
        return False

################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debug = ('debug' in self.pluginPrefs and self.pluginPrefs['debug'])
        self.WFWSWorker = None
        self.WFWebsocketDevCount = 0
        self.stationMetadata = None
        self.dev_map = {} # Map of Smart Weather devices to Indigo devices
        self.last_obs = {}
        self.last_rapid_wind = {}
        self.last_evt_strike = {}
        self.WFUDPWorker = None
        self.WFUDPDevCount = 0

    ########################################
    def launchWiki(self, valuesDict=None, typeId="", targetId=0):
        webbrowser.open('https://github.com/bpennypacker/WeatherFlow-Indigo-Plugin/wiki')
        return valuesDict

    ########################################
    def validatePrefsConfigUi(self, valuesDict):
        errorDict = indigo.Dict()
        isError = False

        if 'websocketsEnabled' in valuesDict and valuesDict['websocketsEnabled'] == True:
            stationID = valuesDict["stationID"]

            if isInt(stationID) == False or int(stationID) <= 0:
                errorDict["stationID"] = "Station ID must be a positive integer"
                isError = True

            url = urls['station'].format(stationID, api_key)
            self.logger.debug("GET " + url)
            try:
                response = requests.get(url)
                self.logger.debug("response: {}".format(response.status_code))
                self.stationMetadata = json.loads(response.content)
                self.logger.debug(json.dumps(self.stationMetadata, sort_keys=True, indent=4, separators=(',', ': ')))
            except Exception as e:
                self.logger.error(traceback.format_exception(*sys.exc_info()))
                self.logger.error(str(e))
                errorDict["stationID"] = "Invalid Station ID. ID is not recognized by WeatherSmart."
                isError = True

        try:
            dateFormat = valuesDict["dateFormat"]
            x = time.strftime(dateFormat, time.localtime(1))
        except:
            errorDict["dateFormat"] = "Invalid Python date format. See https://strftime.org for examples."
            isError = True

        if isError:
            return (False, valuesDict, errorDict)

        return True

    ########################################
    def startup(self):
        self.logger.debug(u"startup called")
        self.queue = Queue.Queue(maxsize=1000)

    ########################################
    def shutdown(self):
        self.logger.debug(u"shutdown called")
        if self.WFWSWorker != None:
            self.WFWSWorker.shutdown()

        if self.WFUDPWorker != None:
            self.WFUDPWorker.shutdown()
        
    ########################################
    def deviceStartComm(self, dev):
        self.logger.debug(u"deviceStartComm({})".format(dev.name))

        props = dev.pluginProps

        if props['dev_type'] == 'websocket':
            self.WFWebsocketDevCount += 1

            if (self.WFWSWorker == None and
                   'websocketsEnabled' in self.pluginPrefs and
                   self.pluginPrefs['websocketsEnabled'] == True):

                self.WFWSWorker = WeatherFlowWebsocketWorker(api_key, self.queue)
                self.WFWSWorker.start()

            map_entry = "{}-{}".format(props['address'], dev.deviceTypeId)
            self.dev_map[map_entry] = dev.id
            self.last_obs[dev.id] = None
            self.last_rapid_wind[dev.id] = None

            if self.WFWSWorker:
                self.WFWSWorker.add_device(props['address'], dev.deviceTypeId)

        elif props['dev_type'] == 'udp':
            self.WFUDPDevCount += 1

            if (self.WFUDPWorker == None and
                    'UDPEnabled' in self.pluginPrefs and
                    self.pluginPrefs['UDPEnabled'] ==True):

                self.WFUDPWorker = WeatherFlowUDPWorker(self.queue)
                self.WFUDPWorker.start()

            map_entry = "{}-{}".format(props['address'], dev.deviceTypeId)
            self.dev_map[map_entry] = dev.id
            self.last_obs[dev.id] = None
            self.last_rapid_wind[dev.id] = None
        else:
            self.logger.error("unknown dev_type '{}'".format(props['dev_type']))

    ########################################
    def deviceStopComm(self, dev):
        self.logger.debug(u"deviceStopComm({})".format(dev.name))

        props = dev.pluginProps

        if props['dev_type'] == 'websocket':
            self.WFWebsocketDevCount -= 1

            map_entry = "{}-{}".format(props['address'], dev.deviceTypeId)

            del self.dev_map[map_entry]
            del self.last_obs[dev.id]
            del self.last_rapid_wind[dev.id]

            if self.WFWSWorker:
                self.WFWSWorker.remove_device(props['address'], dev.deviceTypeId)

            if self.WFWebsocketDevCount < 0:
                self.logger.error('whoops! somehow ended up with < 0 websocket devices... {}'.format(dev.name))
                self.WFWebsocketDevCount = 0

            if self.WFWebsocketDevCount == 0 and self.WFWSWorker:
                self.WFWSWorker.shutdown()
                self.WFWSWorker = None

        elif props['dev_type'] == 'udp':
            self.WFUDPDevCount -= 1

            map_entry = "{}-{}".format(props['address'], dev.deviceTypeId)
            del self.dev_map[map_entry]
            del self.last_obs[dev.id]
            del self.last_rapid_wind[dev.id]

            if self.WFUDPDevCount < 0:
                self.logger.error('whoops! somehow ended up with < 0 UDP devices... {}'.format(dev.name))
                self.WFUDPDevCount = 0

            if self.WFUDPDevCount == 0 and self.WFUDPWorker:
                self.WFUDPWorker.shutdown()
                self.WFUDPWorker = None

        else:
            self.logger.error("unknown dev_type '{}'".format(props['dev_type']))

    ########################################
    def getWebsocketDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        array = [ ]

        filter_list = filter.split('|')

        if self.stationMetadata == None and isInt(self.pluginPrefs['stationID']):
            url = urls['station'].format(self.pluginPrefs['stationID'], api_key)
            self.logger.debug("GET " + url)
            try:
                response = requests.get(url)
                self.logger.debug("response: {}".format(response.status_code))
                self.stationMetadata = json.loads(response.content)
                self.logger.debug(json.dumps(self.stationMetadata, sort_keys=True, indent=4, separators=(',', ': ')))
            except Exception as e:
                self.logger.error(traceback.format_exception(*sys.exc_info()))
                self.logger.error(str(e))
                return []

        try:
            devices = self.stationMetadata['stations'][0]['devices']

            for d in devices:
                if 'device_type' in d and d['device_type'] in filter_list:
                    array.append((d['device_id'], "{} ({})".format(d['device_meta']['name'], d['device_meta']['environment'])))
        except:
            self.logger.error(traceback.format_exception(*sys.exc_info()))
            self.logger.error(str(e))

        return array

    ########################################
    def getUDPDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        array = [ ]

        if self.WFUDPWorker == None:
            return array

        for sn in self.WFUDPWorker.get_serial_numbers():
            if sn.startswith(filter):
                array.append((sn, sn))

        return array

    ########################################
    def _process_message(self, msgtype, token, data):

        if msgtype == MSG_DEBUG:
            self.logger.debug('%s' % (data))
            return

        if msgtype == MSG_ERROR:
            self.logger.error('%s' % (data))
            return

        if msgtype == MSG_WEBSOCKET or msgtype == MSG_UDP:
            suffix = device_suffix[msgtype]
            j = json.loads(data)

            if 'type' not in j:
                jd = json.dumps(j, sort_keys=True, indent=4, separators=(',', ': '))
                self.logger.warn("unrecognized message:\n{}".format(jd))
                return

            if j['type'] in [ "ack",  "connection_opened" ]:
                return

            if j['type'] == "obs_sky":
                dm = "{}-SmartWeatherSky{}".format(token, suffix)
                if dm in self.dev_map:
                    indigo_dev = indigo.devices[self.dev_map[dm]]
                    self.process_obs_sky(indigo_dev, data)

            elif j['type'] == "obs_air":
                dm = "{}-SmartWeatherAir{}".format(token, suffix)
                if dm in self.dev_map:
                    indigo_dev = indigo.devices[self.dev_map[dm]]
                    self.process_obs_air(indigo_dev, data)

            elif j['type'] == "rapid_wind":
                dm = "{}-SmartWeatherRapidWind{}".format(token, suffix)
                if dm in self.dev_map:
                    indigo_dev = indigo.devices[self.dev_map[dm]]
                    self.process_rapid_wind(indigo_dev, data)

            elif j['type'] == "evt_precip":
                for swtype in [ 'SmartWeatherSky', 'SmartWeatherTempest' ] :
                    dm = "{}-{}{}".format(token, swtype, suffix)
                    if dm in self.dev_map:
                        indigo_dev = indigo.devices[self.dev_map[dm]]
                        self.process_evt_precip(indigo_dev, data)

            elif j['type'] == "evt_strike":
                for swtype in [ 'SmartWeatherSky', 'SmartWeatherTempest' ] :
                    dm = "{}-{}{}".format(token, swtype, suffix)
                    if dm in self.dev_map:
                        indigo_dev = indigo.devices[self.dev_map[dm]]
                        self.process_evt_strike(indigo_dev, data)

            elif j['type'] == "obs_st":
                dm = "{}-SmartWeatherTempest{}".format(token, suffix)
                if dm in self.dev_map:
                    indigo_dev = indigo.devices[self.dev_map[dm]]
                    self.process_obs_tempest(indigo_dev, data)

            else:
                jd = json.dumps(j, sort_keys=True, indent=4, separators=(',', ': '))
                self.logger.error("unrecognized event type:\n{}".format(jd))

    ########################################
    def runConcurrentThread(self):
        while True:
            self.debug = ('debug' in self.pluginPrefs and self.pluginPrefs['debug'] == True)

            # Start or stop the UDP worker thread based on the plugin prefs setting
            # And the current state of the thread
            if (self.WFUDPWorker == None and
                    'UDPEnabled' in self.pluginPrefs and
                    self.pluginPrefs['UDPEnabled'] == True):

                self.WFUDPWorker = WeatherFlowUDPWorker(self.queue)
                self.WFUDPWorker.start()
                self.logger.debug("restarted UDP thread")

            elif (self.WFUDPWorker != None and
                     ('UDPEnabled' not in self.pluginPrefs or self.pluginPrefs['UDPEnabled'] == False)):

                self.WFUDPWorker.shutdown()
                self.WFUDPWorker = None
                self.logger.debug("tore down UDP thread")

            # Start or stop the Websocket worker thread based on the plugin prefs setting
            # And the current state of the thread
            if (self.WFWSWorker == None and
                    'websocketsEnabled' in self.pluginPrefs and
                    self.pluginPrefs['websocketsEnabled'] == True):

                self.WFWSWorker = WeatherFlowWebsocketWorker(api_key, self.queue)
                self.WFWSWorker.start()
                self.logger.debug("restarted websocket thread")

                # Register each Indigo Websocket device with the Websocket worker
                for dm in self.dev_map:
                    indigo_dev = indigo.devices[self.dev_map[dm]]
                    props = indigo_dev.pluginProps
                    if props['dev_type'] == 'websocket':
                        self.WFWSWorker.add_device(props['address'], indigo_dev.deviceTypeId)
                        self.logger.debug("re-added device {}".format(indigo_dev.name))

            elif (self.WFWSWorker != None and
                     ('websocketsEnabled' not in self.pluginPrefs or self.pluginPrefs['websocketsEnabled'] == False)):

                self.WFWSWorker.shutdown()
                self.WFWSWorker = None
                self.logger.debug("tore down websocket thread")

            try:
                msg = self.queue.get(block=False)
                msgtype = msg[0]
                mask = msg[1]
                data = msg[2]

                self._process_message(msgtype, mask, data)
                self.sleep(0.1)

            except Queue.Empty as e:
                self.sleep(0.5)
                continue

            except self.StopThread:
                break

    ########################################
    def process_summary(self, data):
        if not 'summary' in data:
            return

        if 'weatherflow' not in indigo.variables.folders:
            indigo.variables.folder.create('weatherflow')

        summary = data['summary']

        for s in summary:
            varname = '{}_{}'.format(data['device_id'], s)

            if varname in indigo.variables:
                v = indigo.variables[varname]
                indigo.variable.updateValue(v, str(summary[s]))
            else:
                fid = indigo.variables.folders['weatherflow']
                indigo.variable.create(varname, str(summary[s]), folder=fid)


    ########################################
    def process_obs_sky(self, dev, data):

        d = json.loads(data)

        last = self.last_obs[dev.id]

        for i in obs_sky_map:
            idx = obs_sky_map[i]
            if idx < len(d['obs'][0]):
               if last == None or last['obs'][0][obs_sky_map[i]] != d['obs'][0][obs_sky_map[i]]:
                   if i in obs_precision:
                       dev.updateStateOnServer(i, d['obs'][0][obs_sky_map[i]], decimalPlaces=obs_precision[i])
                   else:
                       dev.updateStateOnServer(i, d['obs'][0][obs_sky_map[i]])

        # precipitation type, index 12
        idx = 12
        if len(d['obs'][0]) > idx:
            if last == None or last['obs'][0][12] != d['obs'][0][idx]:
                if d['obs'][0][idx] < len(precip_type):
                    pt = precip_type[d['obs'][0][idx]]
                else:
                    pt = "unknown"
                    self.logger.debug("unknown precip type ({})".format(d['obs'][0][idx]))
                dev.updateStateOnServer('precipitation_type', pt)

        # precipitation analysis type, index 16
        idx = 16
        if len(d['obs'][0]) > idx:
            if last == None or last['obs'][0][idx] != d['obs'][0][idx]:
                state = ['none', 'on', 'off']
                if d['obs'][0][idx] < len(state):
                    pat = state[d['obs'][0][idx]]
                else:
                    pat = "unknown ({})".format(d['obs'][0][idx])
                dev.updateStateOnServer('precipitation_analysis_type', pat)

        dateFormat = self.pluginPrefs["dateFormat"]
        dev.updateStateOnServer('formatted_datetime', time.strftime(dateFormat, time.localtime(d['obs'][0][0])))

        self.process_summary(d)

        dev.updateStateOnServer('raw_obs', data)

        self.last_obs[dev.id] = d

    ########################################
    def process_obs_tempest(self, dev, data):

        d = json.loads(data)

        last = self.last_obs[dev.id]

        for i in obs_tempest_map:
            idx = obs_tempest_map[i]
            if idx < len(d['obs'][0]):
                if last == None or last['obs'][0][obs_tempest_map[i]] != d['obs'][0][obs_tempest_map[i]]:
                    if i in obs_precision:
                        dev.updateStateOnServer(i, d['obs'][0][obs_tempest_map[i]], decimalPlaces=obs_precision[i])
                    else:
                        dev.updateStateOnServer(i, d['obs'][0][obs_tempest_map[i]])

        # 13 - obs_st precipitation type
        idx = 13
        if last == None or last['obs'][0][idx] != d['obs'][0][idx]:
            if d['obs'][0][idx] < len(precip_type):
                pt = precip_type[d['obs'][0][idx]]
            else:
                pt = "unknown"
                self.logger.debug("unknown precip type ({})".format(d['obs'][0][idx]))
            dev.updateStateOnServer('precipitation_type', pt)

        # precipitation analysis type, index 20
        idx = 20
        if len(d['obs'][0]) > idx:
            if (last == None or last['obs'][0][20] != d['obs'][0][idx]) and d['obs'][0][idx] != None:
                state = ['none', 'on', 'off']
                if d['obs'][0][idx] < len(state):
                    pat = state[d['obs'][0][idx]]
                else:
                    pat = "unknown ({})".format(d['obs'][0][idx])
                dev.updateStateOnServer('precipitation_analysis_type', pat)

        dateFormat = self.pluginPrefs["dateFormat"]
        dev.updateStateOnServer('formatted_datetime', time.strftime(dateFormat, time.localtime(d['obs'][0][0])))

        self.process_summary(d)

        dev.updateStateOnServer('raw_obs', data)

        self.last_obs[dev.id] = d

    ########################################
    def process_obs_air(self, dev, data):

        d = json.loads(data)

        last = self.last_obs[dev.id]

        for i in obs_air_map:
            idx = obs_air_map[i]
            if idx < len(d['obs'][0]):
                if last == None or last['obs'][0][obs_air_map[i]] != d['obs'][0][obs_air_map[i]]:
                    if i in obs_precision:
                        dev.updateStateOnServer(i, d['obs'][0][obs_air_map[i]], decimalPlaces=obs_precision[i])
                    else:
                        dev.updateStateOnServer(i, d['obs'][0][obs_air_map[i]])

        dateFormat = self.pluginPrefs["dateFormat"]
        dev.updateStateOnServer('formatted_datetime', time.strftime(dateFormat, time.localtime(d['obs'][0][0])))

        self.process_summary(d)

        dev.updateStateOnServer('raw_obs', data)

        self.last_obs[dev.id] = d

    ########################################
    def process_rapid_wind(self, dev, data):

        d = json.loads(data)

        last = self.last_rapid_wind[dev.id]

        for i in rapid_wind_map:
            idx = rapid_wind_map[i]
            if idx < len(d['ob']):
                if last == None or last['ob'][rapid_wind_map[i]] != d['ob'][rapid_wind_map[i]]:
                    if i in obs_precision:
                        dev.updateStateOnServer(i, d['ob'][rapid_wind_map[i]], decimalPlaces=obs_precision[i])
                    else:
                        dev.updateStateOnServer(i, d['ob'][rapid_wind_map[i]])

        dateFormat = self.pluginPrefs["dateFormat"]
        dev.updateStateOnServer('formatted_datetime', time.strftime(dateFormat, time.localtime(d['ob'][0])))

        dev.updateStateOnServer('raw_obs', data)

        self.last_rapid_wind[dev.id] = d

    ########################################
    def process_evt_precip(self, dev, data):

        d = json.loads(data)

        dateFormat = self.pluginPrefs["dateFormat"]
        dev.updateStateOnServer('last_precip_formatted', time.strftime(dateFormat, time.localtime(d['evt'][0])))

        dev.updateStateOnServer('last_precip', d['evt'][0])
        dev.updateStateOnServer('raw_precip', data)

    ########################################
    def process_evt_strike(self, dev, data):

        d = json.loads(data)

        last = None
        if dev.id in self.last_evt_strike:
            last = self.last_evt_strike[dev.id]

        for i in evt_strike_map:
            idx = evt_strike_map[i]
            if idx < len(d['evt']):
                if last == None or last['evt'][evt_strike_map[i]] != d['evt'][evt_strike_map[i]]:
                    if i in obs_precision:
                        dev.updateStateOnServer(i, d['evt'][evt_strike_map[i]], decimalPlaces=obs_precision[i])
                    else:
                        dev.updateStateOnServer(i, d['evt'][evt_strike_map[i]])

        dateFormat = self.pluginPrefs["dateFormat"]
        dev.updateStateOnServer('last_srike_formatted', time.strftime(dateFormat, time.localtime(d['evt'][0])))

        dev.updateStateOnServer('raw_strike', data)

        self.last_evt_strike[dev.id] = d
