#!/bin/bash

set -ev

if [[ -z ${PACKAGE_VERSION} || \
      -z ${ANACONDA_TOKEN} ]] ; then
    echo 'Required environment variable not set!'
    exit -1
fi

# Add conda channels
conda config --add channels bioconda
conda config --add channels ostrokach-forge
conda config --append channels salilab
case "${PACKAGE_VERSION}" in
  *dev*)
    conda config --append channels kimlab/label/dev;
    conda config --append channels kimlab;
  ;;
  *)
    conda config --append channels kimlab;
  ;;
  esac
conda config --append channels https://${KIMLAB_CONDA_LOGIN}@conda.proteinsolver.org


# Update conda and conda-build
conda update conda conda-build
