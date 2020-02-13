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

import os
import sys

from functools import wraps

from cloudify.exceptions import NonRecoverableError
from cloudify.decorators import operation
from cloudify.utils import exception_to_error_cause

from terraform import Terraform
from utils import get_terraform_source


def with_terraform(func):
    @wraps(func)
    def f(*args, **kwargs):
        ctx = kwargs['ctx']
        resource_config = ctx.node.properties['resource_config']
        executable_path = ctx.node.properties['executable_path']
        plugins_dir = ctx.node.properties['plugins_dir']
        if not os.path.exists(executable_path):
            raise NonRecoverableError(
                "Terraform's executable not found in {0}. Please set the "
                "'executable_path' property accordingly.".format(
                    executable_path))
        with get_terraform_source(ctx, resource_config) as terraform_source:
            tf = Terraform(
                ctx.logger,
                executable_path,
                plugins_dir,
                terraform_source,
                variables=resource_config.get('variables'),
                environment_variables=resource_config.get('environment_variables'))
            kwargs['tf'] = tf
            return func(*args, **kwargs)

    return f


def refresh_resources_properties(ctx, state):
    resources = {}
    for resource in state.get('resources', []):
        resources[resource['name']] = resource
    for module in state.get('modules', []):
        for resource_name, resource_def in module.get('resources',
                                                      {}).iteritems():
            resources[resource_name] = resource_def
    ctx.instance.runtime_properties['resources'] = resources


@operation
@with_terraform
def init(ctx, tf, **_):
    """
    Execute `terraform init`.
    """
    try:
        tf.init()
        tf.plan()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed initializing Terraform",
            causes=[exception_to_error_cause(ex, tb)])


@operation
@with_terraform
def apply(ctx, tf, **_):
    """
    Execute `terraform apply`.
    """
    try:
        tf.apply()
        tf_state = tf.state_pull()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed applying",
            causes=[exception_to_error_cause(ex, tb)])
    refresh_resources_properties(ctx, tf_state)


@operation
@with_terraform
def state_pull(ctx, tf, **_):
    """
    Execute `terraform state pull`.
    """
    try:
        tf.refresh()
        tf_state = tf.state_pull()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed pulling state",
            causes=[exception_to_error_cause(ex, tb)])
    refresh_resources_properties(ctx, tf_state)


@operation
@with_terraform
def destroy(ctx, tf, **_):
    """
    Execute `terraform destroy`.
    """
    try:
        tf.destroy()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed destroying",
            causes=[exception_to_error_cause(ex, tb)])


@operation
@with_terraform
def reload(ctx, tf, source, **_):
    """
    Terraform reload plan given new location as input
    """
    try:
        # check the new path provided by input
        if source:
            tf.destroy()
            # clear the runtime properties to fetch new template
            ctx.instance.runtime_properties.pop('terraform_source', None)
            ctx.instance.runtime_properties.pop('last_source_location', None)
            ctx.node.properties['resource_config']['source'] = source
        else:
            raise NonRecoverableError(
                "New source path/URL for Terraform template was not provided")
        # initialize Terraform with new template location
        resource_config = ctx.node.properties['resource_config']
        with get_terraform_source(ctx, resource_config) as terraform_source:
            tf = Terraform(
                ctx.logger,
                tf.binary_path,
                tf.plugins_dir,
                terraform_source,
                variables=resource_config.get('variables'),
                environment_variables=resource_config.get('environment_variables'))
            tf.init()
            tf.plan()
            tf.apply()
            tf_state = tf.state_pull()
            refresh_resources_properties(ctx, tf_state)
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed reloading terraform plan",
            causes=[exception_to_error_cause(ex, tb)])
