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
import copy
import json
import base64
import ntpath
import shutil
import zipfile
import filecmp
import tempfile
import requests
import threading
import subprocess
from io import BytesIO
from contextlib import contextmanager

from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
from cloudify_common_sdk.utils import get_deployment_dir
from cloudify_common_sdk.resource_downloader import unzip_archive
from cloudify_common_sdk.resource_downloader import untar_archive
from cloudify_common_sdk.resource_downloader import get_shared_resource
from cloudify_common_sdk.resource_downloader import TAR_FILE_EXTENSTIONS

try:
    from cloudify.constants import RELATIONSHIP_INSTANCE, NODE_INSTANCE
except ImportError:
    NODE_INSTANCE = 'node-instance'
    RELATIONSHIP_INSTANCE = 'relationship-instance'

from . import TERRAFORM_BACKEND
from .constants import IS_DRIFTED, DRIFTS, STATE, NAME
from ._compat import text_type, StringIO, PermissionDenied, mkdir_p

TERRAFORM_STATE_FILE = 'terraform.tfstate'

MASKED_ENV_VARS = {
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY'
}


def download_file(source, destination):
    run_subprocess(['curl', '-o', source, destination])


def run_subprocess(command,
                   logger=None,
                   cwd=None,
                   additional_env=None,
                   additional_args=None,
                   return_output=False):
    """Execute a shell script or command."""

    logger = logger or ctx.logger
    cwd = cwd or get_node_instance_dir()

    if additional_args is None:
        additional_args = {}

    args_to_pass = copy.deepcopy(additional_args)

    if additional_env:
        passed_env = args_to_pass.setdefault('env', {})
        passed_env.update(os.environ)
        passed_env.update(additional_env)

    printed_args = copy.deepcopy(args_to_pass)
    printed_env = printed_args.get('env', {})
    for env_var in printed_env.keys():
        if env_var in MASKED_ENV_VARS:
            printed_env[env_var] = '****'

    logger.info('Running: command={cmd}, '
                'cwd={cwd}, '
                'additional_args={args}'.format(
                    cmd=command,
                    cwd=cwd,
                    args=printed_args))

    process = subprocess.Popen(
        args=command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=None,
        cwd=cwd,
        **args_to_pass)

    if return_output:
        stdout_consumer = CapturingOutputConsumer(
            process.stdout)
    else:
        stdout_consumer = LoggingOutputConsumer(
            process.stdout, logger, '<out> ')
    stderr_consumer = LoggingOutputConsumer(
        process.stderr, logger, '<err> ')

    return_code = process.wait()
    stdout_consumer.join()
    stderr_consumer.join()

    if return_code:
        raise subprocess.CalledProcessError(return_code, command)

    output = stdout_consumer.buffer.getvalue() if return_output else None
    # Leave this commented in case someone wants to debug.
    # logger.debug('Returning output:\n{output}'.format(
    #     output=output if output is not None else '<None>'))
    return output


def exclude_file(dirname, filename, excluded_files):
    """In _zip_archive, we need to prevent certain files, i.e. the TF binary,
    from being added  to the zip. It's totally unnecessary,
    and also crashes the manager.
    """
    rel_path = os.path.join(dirname, filename)
    for f in excluded_files:
        if not f:
            continue
        elif os.path.isfile(f) and rel_path == f:
            return True
        elif os.path.isdir(f) and f in rel_path:
            return True
    return False


def exclude_dirs(dirname, subdirs, excluded_files):
    """In _zip_archive, we need to prevent certain files, i.e. TF plugins,
    from being added  to the zip. It's totally unnecessary,
    and also crashes the manager.
    """
    rel_subdirs = [os.path.join(dirname, d) for d in subdirs]
    for f in excluded_files:
        if not f:
            continue
        if os.path.isdir(f) and f in rel_subdirs:
            try:
                subdirs.remove(ntpath.basename(f))
            except ValueError:
                pass


def _zip_archive(extracted_source, exclude_files=None, **_):
    """Zip up a folder and all its sub-folders,
    except for those that we wish to exclude.

    :param extracted_source: The location.
    :param exclude_files: A list of files and directories, that we don't
    want to put in the zip.
    :param _:
    :return:
    """
    exclude_files = exclude_files or []
    ctx.logger.debug('Excluding files {l}'.format(l=exclude_files))
    ctx.logger.debug("Zipping {source}".format(source=extracted_source))
    with tempfile.NamedTemporaryFile(suffix=".zip",
                                     delete=False) as updated_zip:
        updated_zip.close()
        with zipfile.ZipFile(updated_zip.name,
                             mode='w',
                             compression=zipfile.ZIP_DEFLATED) as output_file:
            for dir_name, subdirs, filenames in os.walk(extracted_source):
                # Make sure that the files that we don't want
                # to include (e.g. plugins directory) will not be archived.
                exclude_dirs(dir_name, subdirs, exclude_files)
                for filename in filenames:
                    # Extra layer of validation on the excluded files.
                    if not exclude_file(dir_name, filename, exclude_files):
                        # Create the path as we want to archive it to the
                        # archivee.
                        file_to_add = os.path.join(dir_name, filename)
                        # The name of the file in the archive.
                        arc_name = file_to_add[len(extracted_source)+1:]
                        output_file.write(file_to_add, arcname=arc_name)
        archive_file_path = updated_zip.name
    return archive_file_path


def _unzip_archive(archive_path, target_directory, source_path=None, **_):
    """
    Unzip a zip archive.
    """

    # Create a temporary directory.
    # Create a zip archive object.
    # Extract the object.
    target_directory = target_directory if \
        target_directory.endswith('/') else target_directory + '/'

    if source_path:
        if not source_path.endswith('/'):
            source_path = source_path + '/'

    ctx.logger.debug('Extracting {a} {b} to {c}'.format(
        a=archive_path, b=source_path, c=target_directory))

    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        for p in zip_ref.namelist():
            if source_path in p:
                zip_ref.extract(p, target_directory)
                reset_source = os.path.join(target_directory, p)
                reset_target = os.path.join(
                    target_directory, ntpath.basename(p))
                os.rename(reset_source, reset_target)
            else:
                zip_ref.extractall(target_directory)

    return target_directory


def clean_strings(string):
    if isinstance(string, text_type):
        return string.encode('utf-8').rstrip("'").lstrip("'")
    return string


def _file_to_base64(file_path):
    # By getting here, "terraform_source_zip" is the path to a ZIP
    # file containing the Terraform files.
    # We need to encode the contents of the file and set them
    # as a runtime property.
    base64_rep = BytesIO()
    with open(file_path, 'rb') as f:
        base64.encode(f, base64_rep)
    return base64_rep.getvalue().decode('utf-8')


def _create_source_path(source_tmp_path):
    # didn't download anything so check the provided path
    # if file and absolute path or not
    if not os.path.isabs(source_tmp_path):
        # bundled and need to be downloaded from blueprint
        source_tmp_path = ctx.download_resource(source_tmp_path)

    if os.path.isfile(source_tmp_path):
        file_name = source_tmp_path.rsplit('/', 1)[1]
        file_type = file_name.rsplit('.', 1)[1]
        # check type
        if file_type == 'zip':
            return unzip_archive(source_tmp_path)
        elif file_type in TAR_FILE_EXTENSTIONS:
            return untar_archive(source_tmp_path)

    return source_tmp_path


def set_permissions(target_file):
    run_subprocess(
        ['chmod', 'u+x', target_file],
        ctx.logger
    )


def unzip_and_set_permissions(zip_file, target_dir):
    """Unzip a file and fix permissions on the files."""
    ctx.logger.debug('Unzipping into {dir}.'.format(dir=target_dir))

    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        for name in zip_ref.namelist():
            try:
                zip_ref.extract(name, target_dir)
            except PermissionDenied as e:
                raise NonRecoverableError(
                    'Attempted to download a file {name} to {folder}. '
                    'Failed with permission denied {err}.'.format(
                        name=name,
                        folder=target_dir,
                        err=e))
            target_file = os.path.join(target_dir, name)
            ctx.logger.info('Setting executable permission on '
                            '{loc}.'.format(loc=target_file))
            set_permissions(target_file)


def get_instance(_ctx=None, target=False, source=False):
    """Get a CTX instance, either NI, target or source."""
    _ctx = _ctx or ctx
    if _ctx.type == RELATIONSHIP_INSTANCE:
        if target:
            return _ctx.target.instance
        elif source:
            return _ctx.source.instance
        return _ctx.source.instance
    else:  # _ctx.type == NODE_INSTANCE
        return _ctx.instance


def get_node(_ctx=None, target=False):
    """Get a node ctx"""
    _ctx = _ctx or ctx
    if _ctx.type == RELATIONSHIP_INSTANCE:
        if target:
            return _ctx.target.node
        return _ctx.source.node
    else:  # _ctx.type == NODE_INSTANCE
        return _ctx.node


def is_using_existing(target=True):
    """Decide if we need to do this work or not."""
    resource_config = get_resource_config(target=target)
    if not target:
        tf_rel = find_terraform_node_from_rel()
        if tf_rel:
            resource_config = tf_rel.target.instance.runtime_properties.get(
                'resource_config', {})
    return resource_config.get('use_existing_resource', True)


def get_binary_location_from_rel():
    tf_rel = find_terraform_node_from_rel()
    terraform_config = tf_rel.target.node.properties.get(
        'terraform_config', {})
    candidate_a = terraform_config.get('executable_path')
    candidate_b = get_executable_path()
    if candidate_b and os.path.isfile(candidate_b):
        return candidate_b
    if candidate_a and os.path.isfile(candidate_a):
        return candidate_a
    raise NonRecoverableError(
        "Terraform's executable not found in {0} or {1}. Please set the "
        "'executable_path' property accordingly.".format(
            candidate_b, candidate_a))


def find_terraform_node_from_rel():
    return find_rel_by_type(
        ctx.instance, 'cloudify.terraform.relationships.run_on_host')


def find_rel_by_type(node_instance, rel_type):
    rels = find_rels_by_type(node_instance, rel_type)
    return rels[0] if len(rels) > 0 else None


def find_rels_by_type(node_instance, rel_type):
    return [x for x in node_instance.relationships
            if rel_type in x.type_hierarchy]


def install_binary(
        installation_dir,
        executable_path,
        installation_source=None):

    if installation_source:
        installation_zip = os.path.join(installation_dir, 'tf.zip')
        ctx.logger.info(
            'Downloading Terraform from {source} into {zip}.'.format(
                source=installation_source,
                zip=installation_zip))
        download_file(installation_zip, installation_source)
        executable_dir = os.path.dirname(executable_path)
        unzip_and_set_permissions(installation_zip, executable_dir)
        os.remove(installation_zip)
    return executable_path


def get_resource_config(target=False):
    """Get the cloudify.nodes.terraform.Module resource_config"""
    ctx.logger.debug('Getting resource config.')
    instance = get_instance(target=target)
    resource_config = instance.runtime_properties.get('resource_config')
    if resource_config:
        ctx.logger.debug('Retrieved resource config from runtime properties.')
        return resource_config
    node = get_node(target=target)
    ctx.logger.debug('Retrieved resource config from node properties.')
    return node.properties.get('resource_config', {})


def get_terraform_config(target=False):
    """get the cloudify.nodes.terraform or cloudify.nodes.terraform.Module
    terraform_config"""
    ctx.logger.debug('Getting terraform config.')
    instance = get_instance(target=target)
    terraform_config = instance.runtime_properties.get('terraform_config')
    if terraform_config:
        ctx.logger.debug('Retrieved terraform config from runtime properties.')
        return terraform_config
    node = get_node(target=target)
    ctx.logger.debug('Retrieved terraform config from node properties.')
    return node.properties.get('terraform_config', {})


def update_terraform_source_material(new_source, target=False):
    """Replace the terraform_source material with a new material.
    This is used in terraform.reload_template operation."""
    ctx.logger.debug('Updating source material.')
    instance = get_instance(target=target)
    new_source_location = new_source['location']
    source_tmp_path = get_shared_resource(
        new_source_location, dir=get_node_instance_dir(target=target),
        username=new_source.get('username'),
        password=new_source.get('password'))
    ctx.logger.debug('The shared resource path is {loc}'.format(
        loc=source_tmp_path))

    # check if we actually downloaded something or not
    if source_tmp_path == new_source_location:
        source_tmp_path = _create_source_path(source_tmp_path)

    # By getting here we will have extracted source
    # Zip the file to store in runtime
    terraform_source_zip = _zip_archive(source_tmp_path)
    base64_rep = _file_to_base64(terraform_source_zip)
    ctx.logger.info('The before base64_rep size is {size}.'.format(
        size=len(base64_rep)))

    instance.runtime_properties['terraform_source'] = base64_rep
    instance.runtime_properties['last_source_location'] = new_source_location
    ctx.logger.debug('Updated source material {l}.'.format(
        l=new_source_location))
    instance.update()
    return base64_rep


def get_terraform_source_material(target=False):
    """In principle this is the binary data of a zip archive containing the
    Terraform state and plan files.
    However, during the install workflow, this might also be the binary
    data of a zip archive of just the plan files.
    """
    ctx.logger.debug('Getting Terraform source material.')
    instance = get_instance(target=target)
    source = instance.runtime_properties.get('terraform_source')
    if source:
        ctx.logger.debug('Retrieved terraform source material'
                         ' from runtime properties.')
        return source
    resource_config = get_resource_config(target=target)
    source = resource_config.get('source')
    return update_terraform_source_material(source, target=target)


def get_installation_source(target=False):
    """This is the URL or file where we can get the Terraform binary"""
    resource_config = get_resource_config(target=target)
    source = resource_config.get('installation_source')
    if not source:
        raise NonRecoverableError(
            'No download URL for terraform binary executable file was '
            'provided and use_external_resource is False. '
            'Please provide a valid download URL.')
    return source


def get_executable_path(target=False):
    """The Terraform binary executable.
    It should either be: null, in which case it defaults to
    /opt/manager/resources/deployments/{tenant}/{deployment_id}/terraform
    or it will be /usr/bin/terraform, and this should be used as an
    existing resource.
    Any other value will probably not work for the user.
    """
    instance = get_instance(target=target)
    executable_path = instance.runtime_properties.get('executable_path')
    if not executable_path:
        terraform_config = get_terraform_config(target=target)
        executable_path = terraform_config.get('executable_path')
    if not executable_path:
        executable_path = \
            os.path.join(get_node_instance_dir(target=target), 'terraform')
    if not os.path.exists(executable_path) and \
            is_using_existing(target=target):
        node = get_node(target=target)
        terraform_config = node.properties.get('terraform_config', {})
        executable_path = terraform_config.get('executable_path')
    instance.runtime_properties['executable_path'] = executable_path
    ctx.logger.debug('Value executable_path is {loc}.'.format(
        loc=executable_path))
    return executable_path


def get_storage_path(target=False):
    """Where we install all of our terraform files.
    It should always be: /opt/manager/resources/deployments/{tenant}
    /{deployment_id}
    """
    resource_config = get_resource_config(target=target)
    deployment_dir = get_node_instance_dir(target=target)
    storage_path = resource_config.get('storage_path')
    if storage_path and storage_path is not deployment_dir:
        raise NonRecoverableError(
            'The property resource_config.storage_path '
            'is no longer supported.')
    ctx.logger.debug('Value storage_path is {loc}.'.format(
        loc=deployment_dir))
    instance = get_instance(target=target)
    instance.runtime_properties['storage_path'] = deployment_dir
    instance.update()
    return deployment_dir


def get_plugins_dir(target=False):
    """Plugins are installed into this directory.
    It should always be: /opt/manager/resources/deployments/{tenant}
    /{deployment_id}/.terraform/plugins
    """
    resource_config = get_resource_config(target=target)
    storage_path = get_storage_path(target=target)
    plugins_dir = resource_config.get(
        'plugins_dir',
        os.path.join(storage_path, '.terraform', 'plugins'))
    if storage_path not in plugins_dir:
        raise NonRecoverableError(
            'Terraform plugins directory {plugins} '
            'must be a subdirectory of the storage_path {storage}.'.format(
                plugins=plugins_dir, storage=storage_path))
    ctx.logger.debug('Value plugins_dir is {loc}.'.format(
        loc=plugins_dir))
    return plugins_dir


def get_plugins(target=False):
    """These are plugins that the user wishes to install."""
    resource_config = get_resource_config(target=target)
    return resource_config.get('plugins', {})


def get_source_path(target=False):
    resource_config = get_resource_config(target=target)
    return resource_config.get('source_path')


def create_plugins_dir(plugins_dir=None):
    """Create the directory where we will install all the plugins."""
    # Create plugins directory, if needed.
    if plugins_dir:
        if os.path.isdir(plugins_dir):
            ctx.logger.info('Plugins directory already exists: {loc}'.format(
                loc=plugins_dir))
        else:
            ctx.logger.info('Creating plugins directory: {loc}'.format(
                loc=plugins_dir))
            mkdir_p(plugins_dir)
        # store the values in the runtime for safe keeping -> validation
        ctx.instance.runtime_properties['plugins_dir'] = plugins_dir


def remove_dir(folder, desc=''):
    if os.path.isdir(folder):
        ctx.logger.info('Removing {desc}: {dir}'.format(desc=desc, dir=folder))
        shutil.rmtree(folder)
    elif os.path.islink(folder):
        ctx.logger.info('Unlinking: {}'.format(folder))
        os.unlink(folder)
    else:
        ctx.logger.info(
            'Directory {dir} doesn\'t exist; skipping'.format(dir=folder))


def handle_plugins(plugins, plugins_dir, installation_dir):
    """Create the directory where we will download requested plugins into,
    and then download them into it."""
    create_plugins_dir(plugins_dir)
    # Install plugins.
    if not isinstance(plugins, dict):
        raise NonRecoverableError(
            'The plugins value is not valid: {value} '
            'If you wish to use custom Terraform providers must provide a '
            'dictionary in the following format: search.path/provider_name.'
            ''
            'For example:'
            'plugins: \n'
            '  registry.terraform.io/hashicorp/template: '
            'https://releases.hashicorp.com/terraform-provider-template/'
            '2.1.2/'
            'terraform-provider-template_2.1.2_linux_amd64.zip\n'.format(
                value=plugins)
        )
    for plugin_name, plugin_url in plugins.items():
        with tempfile.NamedTemporaryFile(
                suffix=".zip",
                delete=False,
                dir=installation_dir) as plugin_zip:
            plugin_zip.close()
            ctx.logger.info('Downloading Terraform plugin: {url}'.format(
                url=plugin_url))
            download_file(plugin_zip.name, plugin_url)
            unzip_path = os.path.join(plugins_dir, plugin_name)
            mkdir_p(os.path.dirname(unzip_path))
            unzip_and_set_permissions(plugin_zip.name, unzip_path)
            os.remove(plugin_zip.name)


def handle_backend(root_dir):
    resource_config = get_resource_config()
    backend = resource_config.get('backend')
    if backend:
        backend_string = create_backend_string(
            backend['name'], backend.get('options', {}))
        backend_file_path = os.path.join(
            root_dir, '{0}.tf'.format(backend['name']))
        with open(backend_file_path, 'w') as infile:
            infile.write(backend_string)
    ctx.logger.debug('Extracted Terraform files: {loc}'.format(loc=root_dir))


def extract_binary_tf_data(root_dir, data, source_path):
    """Take this encoded data and put it in a zip file and then unzip it."""
    with tempfile.NamedTemporaryFile(dir=root_dir, delete=False) as f:
        base64.decode(StringIO(data), f)
        terraform_source_zip = f.name

    # By getting here, "terraform_source_zip" is the path
    #  to a ZIP file containing the Terraform files.
    _unzip_archive(terraform_source_zip, root_dir, source_path)
    ctx.logger.info('module_root: {loc}'.format(loc=root_dir))
    os.remove(terraform_source_zip)


@contextmanager
def get_terraform_source():
    """Get the JSON/TF files material for the Terraform template.
    Dump in in the file yielded by _yield_terraform_source
    """
    material = get_terraform_source_material()
    return _yield_terraform_source(material)


@contextmanager
def update_terraform_source(new_source):
    """Replace the stored terraform resource template data"""
    material = update_terraform_source_material(new_source)
    return _yield_terraform_source(material)


def _yield_terraform_source(material):
    """Put all the TF resource template data into the work directory,
    let the operations do all their magic,
    and then store it again for later use.
    """
    module_root = get_storage_path()
    handle_backend(module_root)
    source_path = get_source_path()
    extract_binary_tf_data(module_root, material, source_path)
    try:
        yield get_node_instance_dir()
    finally:
        ctx.logger.debug('Re-packaging Terraform files from {loc}'.format(
            loc=module_root))
        archived_file = _zip_archive(
            module_root,
            exclude_files=[get_executable_path(),
                           get_plugins_dir()])
        # Convert the zip archive into base64 for storage in runtime
        # properties.
        base64_rep = _file_to_base64(archived_file)
        os.remove(archived_file)
        ctx.logger.warn('The after base64_rep size is {size}.'.format(
            size=len(base64_rep)))
        ctx.instance.runtime_properties['terraform_source'] = base64_rep
        ctx.instance.runtime_properties['resource_config'] = \
            get_resource_config()


def get_node_instance_dir(target=False, source=False):
    """This is the place where the magic happens.
    We put all our binaries, templates, or symlinks to those files here,
    and then we also run all executions from here.
    """
    instance = get_instance(target=target, source=source)
    folder = os.path.join(
        get_deployment_dir(ctx.deployment.id),
        instance.id
    )
    if not os.path.exists(folder):
        mkdir_p(folder)
    ctx.logger.debug('Value deployment_dir is {loc}.'.format(
        loc=folder))
    return folder


def get_terraform_state_file(ctx):
    """Create or dump the state. This is only used in the
    terraform.refresh_resources operations and it's possible we can
    get rid of it.
    """
    state_file_path = os.path.join(get_storage_path(), TERRAFORM_STATE_FILE)

    encoded_source = get_terraform_source_material()
    storage_path = get_storage_path()
    source_path = get_source_path()

    with tempfile.NamedTemporaryFile(delete=False) as f:
        base64.decode(StringIO(encoded_source), f)
        terraform_source_zip = f.name

    extracted_source = _unzip_archive(terraform_source_zip,
                                      storage_path,
                                      source_path)
    os.remove(terraform_source_zip)

    for dir_name, subdirs, filenames in os.walk(extracted_source):
        for filename in filenames:
            if filename == TERRAFORM_STATE_FILE:
                state_file_from_storage = os.path.join(dir_name, filename)
                if not os.path.exists(state_file_path):
                    ctx.logger.warn(
                        'There is no existing state file {loc}.'.format(
                            loc=state_file_path))
                if not filecmp.cmp(state_file_from_storage, state_file_path):
                    ctx.logger.warn(
                        'State file from storage is not the same as the '
                        'existing state file {loc}. Using any way.'.format(
                            loc=state_file_path))
                shutil.move(os.path.join(dir_name, filename), state_file_path)
                break

    shutil.rmtree(extracted_source)
    return state_file_path


def create_backend_string(name, options):
    # TODO: Get a better way of setting backends.
    option_string = ''
    for option_name, option_value in options.items():
        if isinstance(option_value, text_type):
            option_value = '"%s"' % option_value
        option_string += '    %s = %s\n' % (option_name, option_value)
    backend_block = TERRAFORM_BACKEND % (name, option_string)
    return 'terraform {\n%s\n}' % backend_block


def refresh_resources_properties(state):
    """Store all the resources that we created as JSON in the context."""
    resources = {}
    for resource in state.get('resources', []):
        resources[resource[NAME]] = resource
    for module in state.get('modules', []):
        for name, definition in module.get('resources', {}).items():
            resources[name] = definition
    ctx.instance.runtime_properties['resources'] = resources
    # Duplicate for backward compatibility.
    ctx.instance.runtime_properties[STATE] = resources


def refresh_resources_drifts_properties(plan_json):
    """
        Store all drifts(changes) in resources we created in runtime
        properties.
        The change represent the difference between the current state and
        the desired state.
        The desired state is the infrastructure crated from terraform source.
        means that the tf template is the source of truth.
        :param plan_json: dictionary represent json output of plan,
        as described
        here: https://www.terraform.io/docs/internals/json-format.html#plan
        -representation
    """
    ctx.instance.runtime_properties[IS_DRIFTED] = False
    drifts = {}
    resource_changes = plan_json.get('resource_changes', [])
    for resource_change in resource_changes:
        change = resource_change.get('change', {})
        if change['actions'] not in [['no-op'], ['read']]:
            ctx.instance.runtime_properties[IS_DRIFTED] = True
            drifts[resource_change[NAME]] = change
    ctx.instance.runtime_properties[DRIFTS] = drifts


def is_url(string):
    try:
        return requests.get(string)
    except requests.ConnectionError:
        return False


def handle_previous_source_format(source):
    if isinstance(source, dict):
        return source
    try:
        return json.loads(source)
    except ValueError:
        if is_url(source):
            return {'location': source}
    return source


# Stolen from the script plugin, until this class
# moves to a utils module in cloudify-common.
class OutputConsumer(object):
    def __init__(self, out):
        self.out = out
        self.consumer = threading.Thread(target=self.consume_output)
        self.consumer.daemon = True

    def consume_output(self):
        for line in self.out:
            self.handle_line(line)
        self.out.close()

    def handle_line(self, line):
        raise NotImplementedError("Must be implemented by subclass")

    def join(self):
        self.consumer.join()


class LoggingOutputConsumer(OutputConsumer):
    def __init__(self, out, logger, prefix):
        OutputConsumer.__init__(self, out)
        self.logger = logger
        self.prefix = prefix
        self.consumer.start()

    def handle_line(self, line):
        self.logger.info('{0}{1}'.format(text_type(self.prefix),
                                         line.decode('utf-8').rstrip('\n')))


class CapturingOutputConsumer(OutputConsumer):
    def __init__(self, out):
        OutputConsumer.__init__(self, out)
        self.buffer = StringIO()
        self.consumer.start()

    def handle_line(self, line):
        self.buffer.write(line.decode('utf-8'))

    def get_buffer(self):
        return self.buffer
