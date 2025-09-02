FROM ghcr.io/maplibre/martin

COPY config.yaml .

# use martin-cp to generate mbtiles from the data
COPY generate_mbtiles.sh .
COPY greenprint-tiles.sh .

RUN chmod +x generate_mbtiles.sh
RUN chmod +x greenprint-tiles.sh

ENTRYPOINT ["/usr/local/bin/martin", "-c", "/config.yaml"]