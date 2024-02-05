#!/bin/bash

TABLE=$1
NAME=$2

echo $TABLE;
echo $NAME;

martin-cp  --output-file $TABLE.mbtiles \
           --mbtiles-type normalized     \
           "--bbox=-80.37,40.20,-79.695,40.68"      \
           --concurrency 4 \
           --min-zoom 7                  \
           --max-zoom 20                \
           --source $TABLE          \
           --on-duplicate=override \
           --set-meta name=$NAME \
           $DATABASE_URL


# BOX(-80.3606041689498 40.194292120892,-79.6889780963336 40.674232061388)