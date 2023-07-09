# Notice
For various personal reasons I am no longer able to support this Indigo plug-in (in part becuase I no longer use Indigo). If somebody is willing and able to take over ownership of this project I am more than happy to hand the reigns over.

# WeatherFlow-Indigo-Plugin
Indigo Plugin for obtaining weather data from WeatherFlow

This plugin lets you incorporate WeatherFlow data into Indigo in multiple ways. You can obtain curated weather data from WeatherFlow servers and/or raw weathr data from your own WeatherFlow devices on the same network as your Indigo server.

For more information on WeatherFlow devices please [visit their website](https://weatherflow.com/).

For more information on installing and using this plugin [see the wiki for the plugin](https://github.com/bpennypacker/WeatherFlow-Indigo-Plugin/wiki).

## Release history

### Version 0.3.3
Released: 2022-01-03

* Fixed indexing of Tempest observations

### Version 0.3.2
Released: 2021-02-28

* Fixed ability to create Tempest rapid wind UDP devices

### Version 0.3.1
Released: 2021-01-25

* Fixed bug preventing new "mode" state from being seen by Indigo
* Fixed wiki URL

### Version 0.3.0
Released: 2021-01-13

* Added mode state to websocket devices
* Added support for Personal Access Tokens
* Fixed a small bug in an exception handler

### Version 0.2.3 
Released: 2020-07-16

* Improve error handling in validating Station ID's
* Fix pressure conversions
* Fix processing of Tempest UDP observations

### Version 0.2.2 
Released: 2020-07-14

Properly handle empty/null values in observations

### Version 0.2.1
Released: 2020-06-22

Fixed typo in formatted last lightning strike state

### Version 0.2.0
Released: 2020-06-02

Added ability to customize the "State" column in the Indigo Devices display.

### Version 0.1.3
Released: 2020-05-29

Fixed observation mappings

### Version 0.1.2
Released: 2020-05-29

Fixed unit conversions in wind & lightning events

### Version 0.1.1
Released: 2020-05-29

Fixed lookups of new property configuration options

### Version 0.1.0
Released: 2020-05-28

Added support to specify units for temperature, pressure, wind speed & direction, rain and distances.

### Version 0.0.3
Released: 2020-05-27

Added missing values from Tempest Websocket observations.

Added support for undocumented "summary" data by way of dynamic Indigo variables (see wiki for details)

### Version 0.0.2
Released: 2020-05-24

Added support for Tempest devices

### Version 0.0.1
Released: 2019-12-24

Initial release
