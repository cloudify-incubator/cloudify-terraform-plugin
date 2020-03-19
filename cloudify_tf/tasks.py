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
import tempfile
import shutil
import sys
import zipfile

from functools import wraps

from cloudify.exceptions import NonRecoverableError
from cloudify.decorators import operation
from cloudify.utils import exception_to_error_cause

from terraform import Terraform
from utils import (get_terraform_source, get_terraform_state_file,
                   move_state_file, run_subprocess, unzip_archive)


def with_terraform(func):
    @wraps(func)
    def f(*args, **kwargs):
        ctx = kwargs['ctx']
        resource_config = ctx.node.properties['resource_config']
        with get_terraform_source(ctx, resource_config) as terraform_source:
            tf = Terraform.from_ctx(ctx, terraform_source)
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
def reload_template(ctx, source, destroy_previous, **_):
    """
    Terraform reload plan given new location as input
    """
    try:
        if source:
            state_file = None
            # if we want to destroy previous: no need to preserve the state file
            # by default the state file will be used if no remote backend
            if destroy_previous:
                resource_config = ctx.node.properties['resource_config']
                with get_terraform_source(ctx, resource_config) as terraform_source:
                    tf = Terraform.from_ctx(ctx, terraform_source)
                    tf.destroy()
            else:
                # extract the state file from previous stored source
                state_file = get_terraform_state_file(ctx)

            # initialize new location to apply terraform
            ctx.instance.runtime_properties.pop('terraform_source', None)
            ctx.instance.runtime_properties.pop('last_source_location', None)
            ctx.node.properties['resource_config']['source'] = source

            resource_config = ctx.node.properties['resource_config']
            with get_terraform_source(ctx, resource_config) as terraform_source:
                tf = Terraform.from_ctx(ctx, terraform_source)
                tf.init()
                if state_file:
                    move_state_file(state_file, terraform_source)
                tf.plan()
                tf.apply()
                tf_state = tf.state_pull()
                refresh_resources_properties(ctx, tf_state)
        else:
            raise NonRecoverableError(
                "New source path/URL for Terraform template was not provided")

    except Exception as ex:
        _, _, tb = sys.exc_info()
        raise NonRecoverableError(
            "Failed reloading Terraform plan",
            causes=[exception_to_error_cause(ex, tb)])


def is_using_existing(ctx):
    return ctx.node.properties['use_existing_resource']


def skip_if_existing(func):
    @wraps(func)
    def f(*args, **kwargs):
        ctx = kwargs['ctx']
        if not is_using_existing(ctx):
            return func(*args, **kwargs)
    return f


@operation
def install(ctx, **_):
    def _unzip_and_set_permissions(zip_file, target_dir):
        ctx.logger.info("Unzipping into %s", target_dir)
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            for name in zip_ref.namelist():
                zip_ref.extract(name, target_dir)
                target_file = os.path.join(target_dir, name)
                ctx.logger.info("Setting executable permission on %s", target_file)
                run_subprocess(
                    ['chmod', 'u+x', target_file],
                    ctx.logger
                )

    executable_path = ctx.node.properties['executable_path']
    installation_temp_dir = tempfile.mkdtemp()
    try:
        if not is_using_existing(ctx):
            if os.path.isfile(executable_path):
                ctx.logger.info(
                    "Terraform executable already found at %s; skipping installation of executable",
                    executable_path)
            else:
                installation_source = ctx.node.properties['installation_source']
                installation_zip = os.path.join(installation_temp_dir, 'tf.zip')

                ctx.logger.info("Downloading Terraform from %s into %s", installation_source, installation_zip)
                run_subprocess(
                    ['curl', '-o', installation_zip, installation_source],
                    ctx.logger
                )
                executable_dir = os.path.dirname(executable_path)
                _unzip_and_set_permissions(installation_zip, executable_dir)

        # Create plugins directory, if needed.
        plugins_dir = ctx.node.properties['plugins_dir']
        if plugins_dir:
            if os.path.isdir(plugins_dir):
                ctx.logger.info("Plugins directory already exists: %s", plugins_dir)
            else:
                ctx.logger.info("Creating plugins directory: %s", plugins_dir)
                os.makedirs(plugins_dir)

        # Install plugins.
        plugins = ctx.node.properties['plugins']
        for plugin in plugins:
            with tempfile.NamedTemporaryFile(
                    suffix=".zip",
                    delete=False,
                    dir=installation_temp_dir) as plugin_zip:
                plugin_zip.close()
                ctx.logger.info("Downloading Terraform plugin: %s", plugin)
                run_subprocess(
                    ['curl', '-o', plugin_zip.name, plugin],
                    ctx.logger
                )
                _unzip_and_set_permissions(plugin_zip.name, plugins_dir)

        # Create storage path, if specified.
        storage_path = ctx.node.properties['storage_path']
        if storage_path:
            if os.path.isdir(storage_path):
                ctx.logger.info("Storage directory already exists: %s", storage_path)
            else:
                ctx.logger.info("Creating storage directory: %s", storage_path)
                os.makedirs(storage_path)
    finally:
        if installation_temp_dir:
            shutil.rmtree(installation_temp_dir)


@operation
@skip_if_existing
def uninstall(ctx, **_):
    executable_path = ctx.node.properties['executable_path']
    ctx.logger.info("Removing executable: %s", executable_path)
    os.remove(executable_path)

    for property_name, property_desc in [
        ('plugins_dir', 'plugins directory'),
        ('storage_path', 'storage_directory')
    ]:
        dir_to_delete = ctx.node.properties[property_name]
        if os.path.isdir(dir_to_delete):
            ctx.logger.info("Removing %s: %s", property_desc, dir_to_delete)
            shutil.rmtree(dir_to_delete)
        else:
            ctx.logger.info("Directory %s doesn't exist; skipping", dir_to_delete)
