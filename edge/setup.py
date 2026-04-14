from setuptools import find_packages, setup

package_name = "auxin_edge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/auxin_edge.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Edwin Redhead",
    maintainer_email="edwin@auxin.dev",
    description="ROS2 edge nodes for Auxin Automata",
    license="MIT",
    entry_points={
        "console_scripts": [
            "telemetry_bridge_node = auxin_edge.telemetry_bridge_node:main",
            "safety_watchdog_node = auxin_edge.safety_watchdog_node:main",
        ],
    },
)
