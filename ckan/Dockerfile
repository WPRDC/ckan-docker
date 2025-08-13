FROM ckan/ckan-base:2.11

# Install any extensions needed by your CKAN instance
# See Dockerfile.dev for more details and examples


# Install datapusher-plus requirements, including qsv
USER root
RUN apt update
RUN apt install curl zip unzip python3-virtualenv python3-dev python3-pip python3-wheel build-essential libxslt1-dev libxml2-dev zlib1g-dev git libffi-dev libpq-dev uchardet --yes

# Install QSV as deb pacakage - the version i was getting was behind (5.10) when 6 is out and what dpp 2.0.0 expects
RUN apt install gnupg --yes
RUN wget -O - https://dathere.github.io/qsv-deb-releases/qsv-deb.gpg | gpg --dearmor -o /usr/share/keyrings/qsv-deb.gpg
RUN echo "deb [signed-by=/usr/share/keyrings/qsv-deb.gpg]  https://dathere.github.io/qsv-deb-releases ./" | tee /etc/apt/sources.list.d/qsv.list
RUN apt update # add qsv release
RUN apt install qsv qsv-datapusher-plus

# WPRDC-modified plugins

### Datapusher Plus ###
RUN pip3 install -e git+https://github.com/wprdc/datapusher-plus.git@main#egg=datapusher-plus && \
    pip3 install -r  ${APP_DIR}/src/datapusher-plus/requirements.txt

### DCAT ###
RUN  pip3 install -e git+https://github.com/ckan/ckanext-dcat.git#egg=ckanext-dcat && \
     pip3 install -r ${APP_DIR}/src/ckanext-dcat/requirements.txt

### Scheming ###
RUN  pip3 install -e 'git+https://github.com/ckan/ckanext-scheming.git@master#egg=ckanext-scheming'

### PDF View ###
RUN pip3 install ckanext-pdfview

### Geoview ###
RUN pip3 install -e git+https://github.com/ckan/ckanext-geoview.git#egg=ckanext-geoview

### Office Docs ###
RUN pip3 install -e git+https://github.com/jqnatividad/ckanext-officedocs.git#egg=ckanext-officedocs

### Featured Views ###
RUN pip3 install -e git+https://github.com/OpenGov-OpenData/ckanext-featuredviews.git#egg=ckanext-featuredviews

### DataJSON ###
RUN pip3 install -e git+https://github.com/WPRDC/ckanext-datajson.git#egg=ckanext-datajson && \
    pip3 install -r ${APP_DIR}/src/ckanext-datajson/requirements.txt

### OData ###
RUN pip install -e git+https://github.com/WPRDC/ckanext-odata.git#egg=ckanext-odata

### Dataspatial ###
RUN pip install -e git+https://github.com/WPRDC/ckanext-dataspatial.git#egg=ckanext-dataspatial && \
    pip3 install -r ${APP_DIR}/src/ckanext-dataspatial/requirements.txt

# Install Theme
RUN pip install -e git+https://github.com/WPRDC/ckanext-wprdctheme.git#egg=ckanext-wprdctheme

# Copy custom initialization scripts
COPY --chown=ckan-sys:ckan-sys docker-entrypoint.d/* /docker-entrypoint.d/

# Copy list of allowed functions for sql search
COPY --chown=ckan-sys:ckan-sys allowed_functions_file.txt ${APP_DIR}/

# Apply any patches needed to CKAN core or any of the built extensions (not the
# runtime mounted ones)
COPY --chown=ckan-sys:ckan-sys patches ${APP_DIR}/patches

USER ckan

RUN for d in $APP_DIR/patches/*; do \
        if [ -d $d ]; then \
            for f in `ls $d/*.patch | sort -g`; do \
                cd $SRC_DIR/`basename "$d"` && echo "$0: Applying patch $f to $SRC_DIR/`basename $d`"; patch -p1 < "$f" ; \
            done ; \
        fi ; \
    done
