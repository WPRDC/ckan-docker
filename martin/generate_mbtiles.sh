#!/bin/bash

TABLE=$1
NAME=$2

echo $TABLE;
echo $NAME;

martin-cp  --output-file $NAME.mbtiles \
           --mbtiles-type normalized \
           "--bbox=-80.37,40.20,-79.695,40.68" \
           --concurrency 4 \
           --min-zoom 14 \
           --max-zoom 20 \
           --auto-bounds calc \
           --source $TABLE \
           --on-duplicate=override \
           --set-meta name=$NAME \
           $DATABASE_URL


# BOX(-80.3606041689498 40.194292120892,-79.6889780963336 40.674232061388)


martin-cp  --output-file allegheny-greenways.mbtiles \
           --mbtiles-type normalized \
           "--bbox=-80.37,40.20,-79.695,40.68" \
           --concurrency 4 \
           --min-zoom 9 \
           --max-zoom 18 \
           --auto-bounds skip \
           --source 0335f47a-ed05-4664-8ba3-7ddffd6828bc \
           --on-duplicate=override \
           --set-meta name=allegheny-greenways \
           postgresql://ckan:WSaCryXnaPz4Pdaq@ckan.cluster-c830ppsohcx5.us-east-1.rds.amazonaws.com:5432/datastore_copy


