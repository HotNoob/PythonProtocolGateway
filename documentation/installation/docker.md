### Use Docker
- ```docker build . -t protocol_gateway ```
- ```docker run --device=/dev/ttyUSB0 protocol_gateway```

### Use Docker Image
- ``` docker pull hotn00b/pythonprotocolgateway ``` 
- ```docker run -v $(pwd)/config.cfg:/app/config.cfg --device=/dev/ttyUSB0 hotn00b/pythonprotocolgateway```

[Docker Image Repo](https://hub.docker.com/r/hotn00b/pythonprotocolgateway)