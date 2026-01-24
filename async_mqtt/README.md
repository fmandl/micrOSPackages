# micrOS Application: async\_mqtt

micrOS MQTT Module is an asynchronous messaging and remote control layer for MicroPython
devices that connects them to an MQTT broker for real-time communication.
It enables secure publishing and subscription to device-specific topics,
executes load module commands from incoming messages, and automatically returns
JSON-formatted responses, making micrOS devices easy to monitor, automate,
and control over the network.

## Installation

```
pacman install "github:BxNxM/micrOSPackages/async_mqtt"
```

> Uninstall:

```
pacman uninstall "async_mqtt"
```

> Everything will be installed under `/lib/async_mqtt/*` and `/modules/LM_*`

## MicroPython Docs `package.json` structure and `mip`

[packages](https://docs.micropython.org/en/latest/reference/packages.html)

## Usage

### **load** function - load the app into memory

```commandline
mqtt_client load username:str password:str server_ip:str server_port:str='1883' qos:int=1
```

### **do** function - run example function

```commandline
mqtt_client publish topic:str message:str retain=False
```

[documentation](https://htmlpreview.github.io/?https://github.com/BxNxM/micrOS/blob/master/micrOS/client/sfuncman/sfuncman.html#mqtt_client)

## Dependencies

Autoinstalled external dependency

```
github:peterhinch/micropython-mqtt
```

