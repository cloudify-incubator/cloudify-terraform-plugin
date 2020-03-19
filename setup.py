########
# Copyright (c) 2018 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from setuptools import setup

setup(
    name='cloudify-terraform-plugin',
    version='0.8',
    author='Cloudify',
    author_email='hello@cloudify.co',
    description='Enables Support of Terraform',
    packages=['cloudify_tf', 'cloudify_tf/terraform'],
    license='LICENSE',
    install_requires=[
        'cloudify-common>=4.5.5',
        'pyyaml==3.10',
        'requests>=2.7.0,<3.0'
    ]
)
