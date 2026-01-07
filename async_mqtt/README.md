# micrOS Application: async\_mqtt

Short description about the application...

## Installation

```
pacman download "github:BxNxM/micrOSPackages/async_mqtt"
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

```
github:peterhinch/micropython-mqtt
```

