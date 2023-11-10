#############################
### Build DataPusher Plus ###
#############################
FROM ubuntu:jammy

ARG ARCHITECTURE=x86_64-unknown-linux-gnu
ENV ARCH=$ARCHITECTURE

# Version Numbers
ENV QSV_VERSION="0.118.0"
ENV DPP_VERSION="0.15.0"

# Set timezone
ENV TZ="America/New_York"
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Set Locale
ENV LC_ALL=en_US.UTF-8

ENV SRC_DIR=/srv/app/src
ENV VENV=/usr/lib/ckan/dpplus_venv
ENV CFG_DIR=/etc/ckan/datapusher


WORKDIR ${SRC_DIR}
RUN chown -R www-data:www-data ${SRC_DIR}

# Set the locale          
RUN apt-get update
RUN apt-get install --no-install-recommends -y locales
RUN sed -i "/$LC_ALL/s/^# //g" /etc/locale.gen
RUN dpkg-reconfigure --frontend=noninteractive locales 
RUN update-locale LANG=${LC_ALL}

# Instal apt-utils
RUN apt-get install --no-install-recommends -y \
    apt-utils \
    python3-venv \
    python3-dev \
    python3 \
    build-essential \
    libxslt1-dev \
    libxml2-dev \
    libffi-dev \
    wget \
    curl \
    unzip \
    python3-pip \
    git\
    libpq-dev\
    file \
    tzdata

RUN apt-get install -y postgresql-client
#install qsv
RUN wget https://github.com/jqnatividad/qsv/releases/download/${QSV_VERSION}/qsv-${QSV_VERSION}-${ARCH}.zip -P /tmp
RUN unzip /tmp/qsv-${QSV_VERSION}-${ARCH}.zip  -d /tmp
RUN rm /tmp/qsv-${QSV_VERSION}-${ARCH}.zip
RUN mv /tmp/qsv* /usr/local/bin

#python env setup; link python3 to python cmd; make venv; install uwsgi;
RUN ln -s /usr/bin/python3 /usr/bin/python
RUN python -m venv ${VENV}
RUN ${VENV}/bin/pip install uwsgi python-dateutil

#INSTALL DATAPUSHER-PLUS FROM SOURCE REPO
RUN git clone --branch ${DPP_VERSION} https://github.com/datHere/datapusher-plus

# APPLY PATCHES
COPY patches ${SRC_DIR}/patches

RUN for d in $SRC_DIR/patches/*; do \
        if [ -d $d ]; then \
            for f in `ls $d/*.patch | sort -g`; do \
                cd $SRC_DIR/`basename "$d"` && echo "$0: Applying patch $f to $SRC_DIR/`basename $d`"; patch -p1 < "$f" ; \
            done ; \
        fi ; \
    done


RUN cd ${SRC_DIR}/datapusher-plus && \
   ${VENV}/bin/pip install -r requirements-dev.txt && \
   ${VENV}/bin/pip install tzdata --upgrade && \
   ${VENV}/bin/pip install -e .


#SETUP CONFIG/SETTINGS.PY
RUN mkdir -p ${CFG_DIR}
COPY ./.env ${CFG_DIR}/.env
ENV JOB_CONFIG=${CFG_DIR}/.env

RUN curl https://raw.githubusercontent.com/dathere/datapusher-plus/${DPP_VERSION}/deployment/datapusher-uwsgi.ini -o ${CFG_DIR}/uwsgi.ini

COPY ./entrypoint/startup.sh /startup.sh

USER www-data

ENTRYPOINT ["/bin/sh", "/startup.sh"]

EXPOSE 8800
