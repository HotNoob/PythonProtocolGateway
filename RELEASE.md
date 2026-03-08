things todo to perform a release.

can try to automate some of these later.

GitHub - https://github.com/HotNoob/PythonProtocolGateway/releases
PyPi Package - https://pypi.org/project/python-protocol-gateway/
```
pyproject.toml -> version
defs/common.py -> version
```
```
python -m build
python -m twine upload dist/*
```


HomeAssistant repo - https://github.com/HotNoob/python-protocol-gateway-hass-addon
```
https://github.com/HotNoob/python-protocol-gateway-hass-addon/blob/master/python-protocol-gateway/Dockerfile
```


Docker Image - https://hub.docker.com/r/hotn00b/pythonprotocolgateway
```
wsl
docker login -u hotn00b
```
```
docker pull hotn00b/pythonprotocolgateway:latest
docker tag hotn00b/pythonprotocolgateway:latest hotn00b/pythonprotocolgateway:v1.1.9
docker push hotn00b/pythonprotocolgateway:v1.1.9
```
```
docker build -t hotn00b/pythonprotocolgateway:latest .
docker push hotn00b/pythonprotocolgateway:latest
```