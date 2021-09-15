import os

from setuptools import setup

thelibFolder = os.path.dirname(os.path.realpath(__file__))
requirementPath = thelibFolder + '/requirements_wo_data_collector.txt'
if os.path.isfile(requirementPath):
    with open(requirementPath) as f:
        install_requires = f.read().splitlines()
setup(
    name='sarad_registration_server',
    version='0.0.1',
    packages=['registrationserver'],
    install_requires=install_requires,
)
