from setuptools import find_packages, setup
import os
from glob import glob
package_name = 'rov_system'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob(os.path.join('launch', '*launch.[pxy][yma]*'))),
    ],
    install_requires=['setuptools',
                      'psycopg2-binary'
                      ],
    zip_safe=True,
    maintainer='sirine',
    maintainer_email='sirine@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'rov_simulator = rov_system.rov_simulator:main',
            'rov_publisher = rov_system.rov_publisher:main',
            'rov_subscriber_syncer = rov_system.rov_subscriber_syncer:main',
            'mission_setup_node = rov_system.mission_setup_node:main',
            'raw_db_ingestion_node = rov_system.raw_db_ingestion_node:main',
            'anode_node = rov_system.anode_node:main',
        ],
    },
)
