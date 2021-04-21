########
# Copyright (c) 2018-2020 GigaSpaces Technologies Ltd. All rights reserved
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

from cloudify.decorators import operation
from cloudify.exceptions import NonRecoverableError
from cloudify.utils import exception_to_error_cause

from . import utils
from ._compat import mkdir_p
from .decorators import (
    with_terraform,
    skip_if_existing)
from .terraform import Terraform


@operation
@with_terraform
def apply(ctx, tf, **_):
    """
    Execute `terraform apply`.
    """
    if ctx.workflow_id == 'update':
        resource_config = utils.get_resource_config()
        source = resource_config.get('source')
        reload_template(source, destroy_previous=False, ctx=ctx, tf=tf)
    else:
        _apply(tf)


def _apply(tf):
    try:
        tf.init()
        tf.plan()
        tf.apply()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed applying",
            causes=[exception_to_error_cause(ex, tb)])


@operation
@with_terraform
def state_pull(ctx, tf, **_):
    """
    Execute `terraform state pull`.
    """
    _state_pull(tf)


def _state_pull(tf):
    try:
        tf.refresh()
        tf_state = tf.state_pull()
        plan_json = tf.plan_and_show()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed pulling state",
            causes=[exception_to_error_cause(ex, tb)])
    utils.refresh_resources_properties(tf_state)
    utils.refresh_resources_drifts_properties(plan_json)


@operation
@with_terraform
def destroy(ctx, tf, **_):
    """
    Execute `terraform destroy`.
    """
    _destroy(tf)
    _state_pull(tf)
    for runtime_property in ['terraform_source',
                             'last_source_location',
                             'resource_config']:
        ctx.instance.runtime_properties.pop(runtime_property, None)


def _destroy(tf):
    try:
        tf.init()
        tf.plan()
        tf.destroy()
    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed destroying",
            causes=[exception_to_error_cause(ex, tb)])


@operation
@with_terraform
def reload_template(source, destroy_previous, ctx, tf, **_):
    """
    Terraform reload plan given new location as input
    """
    if not source:
        raise NonRecoverableError(
            "New source path/URL for Terraform template was not provided")

    source = utils.handle_previous_source_format(source)

    if destroy_previous:
        destroy(tf=tf, ctx=ctx)

    with utils.update_terraform_source(source) as terraform_source:
        new_tf = Terraform.from_ctx(ctx, terraform_source)
        _apply(new_tf)
        ctx.instance.runtime_properties['resource_config'] = \
            utils.get_resource_config()
        _state_pull(new_tf)


@operation
@skip_if_existing
def install(ctx, **_):
    installation_dir = utils.get_node_instance_dir()
    executable_path = utils.get_executable_path()
    plugins = utils.get_plugins()
    plugins_dir = utils.get_plugins_dir()
    installation_source = utils.get_installation_source()

    if os.path.isfile(executable_path):
        ctx.logger.info(
            'Terraform executable already found at {path}; '
            'skipping installation of executable'.format(
                path=executable_path))
    else:
        ctx.logger.warn('You are requesting to write a new file to {loc}. '
                        'If you do not have sufficient permissions, that '
                        'installation will fail.'.format(
                            loc=executable_path))
        utils.install_binary(
            installation_dir, executable_path, installation_source)

    # store the values in the runtime for safe keeping -> validation
    ctx.instance.runtime_properties['executable_path'] = executable_path
    utils.handle_plugins(plugins, plugins_dir, installation_dir)


@operation
@skip_if_existing
def uninstall(ctx, **_):
    terraform_config = utils.get_terraform_config()
    resource_config = utils.get_resource_config()
    exc_path = terraform_config.get('executable_path', '')
    system_exc = resource_config.get('use_existing_resource')

    if os.path.isfile(exc_path):
        if system_exc:
            ctx.logger.info(
                'Not removing Terraform installation at {loc} as'
                'it was provided externally'.format(loc=exc_path))
        else:
            ctx.logger.info('Removing executable: {path}'.format(
                path=exc_path))
            os.remove(exc_path)

    for property_name, property_desc in [
        ('plugins_dir',
         'plugins directory'),
        ('storage_path',
         'storage_directory')]:
        dir_to_delete = terraform_config.get(property_name, None)
        if dir_to_delete:
            utils.remove_dir(dir_to_delete, property_desc)


@operation
def set_directory_config(ctx, **_):
    exc_path = utils.get_executable_path(target=True)
    plugins_dir = utils.get_plugins_dir(target=True)
    storage_path = utils.get_storage_path(target=True)
    deployment_terraform_dir = os.path.join(storage_path,
                                            '.terraform')
    resource_node_instance_dir = utils.get_node_instance_dir(source=True)
    if not os.path.exists(resource_node_instance_dir):
        mkdir_p(resource_node_instance_dir)
    resource_terraform_dir = os.path.join(resource_node_instance_dir,
                                          '.terraform')
    resource_plugins_dir = plugins_dir.replace(
        ctx.target.instance.id, ctx.source.instance.id)
    resource_storage_dir = storage_path.replace(
        ctx.target.instance.id, ctx.source.instance.id)

    if utils.is_using_existing(target=True):
        # We are going to use a TF binary at another location.
        # However, we still need to make sure that this directory exists.
        # Otherwise TF will complain. It does not create it.
        # In our other scenario, a symlink is created.
        mkdir_p(resource_terraform_dir)
    else:
        # We don't want to put all the plugins for all the node instances in a
        # deployment multiple times on the system. So here,
        # we already stored it once on the file system, and now we create
        # symlinks so other deployments can use it.
        # TODO: Possibly put this in "apply" and remove the relationship in
        # the future.

        ctx.logger.info('Creating link {src} {dst}'.format(
            src=deployment_terraform_dir, dst=resource_terraform_dir))
        os.symlink(deployment_terraform_dir, resource_terraform_dir)

    ctx.logger.info("setting executable_path to {path}".format(
        path=exc_path))
    ctx.logger.info("setting plugins_dir to {dir}".format(
        dir=resource_plugins_dir))
    ctx.logger.info("setting storage_path to {dir}".format(
        dir=resource_storage_dir))
    ctx.source.instance.runtime_properties['executable_path'] = \
        exc_path
    ctx.source.instance.runtime_properties['plugins_dir'] = \
        resource_plugins_dir
    ctx.source.instance.runtime_properties['storage_path'] = \
        resource_storage_dir
