FROM alpine:3.18
RUN apk add python3 py-pip -q
COPY . /app
WORKDIR /app
RUN pip install flask
EXPOSE 5000
ENTRYPOINT ["python", "app.py"]
