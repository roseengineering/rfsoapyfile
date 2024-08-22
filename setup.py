from setuptools import setup, find_packages

setup(
    name='soapyfile',
    version='0.1.0',
    author='George Magiros',
    author_email='gmagiros@gmail.com',
    url='https://github.com/roseengineering/rfsoapyfile',
    description='Record SDR to wav file using soapysdr library',
    long_description='Record SDR to wav file using soapysdr library',
    long_description_content_type="text/markdown",
    license='MIT',
    packages=find_packages(),
    entry_points={
            'console_scripts': [ 'soapyfile = soapyfile:main' ]
    },
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ),
    keywords='soapyfile',
    install_requires=[
        "numpy",
    ],
    zip_safe=False
)
