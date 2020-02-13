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

from contextlib import contextmanager
import tempfile
import base64
import threading
import zipfile
import os
from io import BytesIO
import StringIO
import shutil
import time

import requests

from . import TERRAFORM_BACKEND


def unzip_archive(ctx, archive_path, storage_path, **_):
    """
    Unzip a zip archive.
    """

    # Create a temporary directory.
    # Create a zip archive object.
    # Extract the object.
    ctx.logger.info("Extracting %s to %s", archive_path, storage_path)
    directory_to_extract_to = tempfile.mkdtemp(dir=storage_path)
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        zip_ref.extractall(directory_to_extract_to)

    return directory_to_extract_to


def clean_strings(string):
    if isinstance(string, unicode):
        return string.encode('utf-8').rstrip("'").lstrip("'")
    return string


@contextmanager
def get_terraform_source(ctx, _resource_config):
    def _file_to_base64(file_path):
        base64_rep = BytesIO()
        with open(file_path, 'rb') as f:
            base64.encode(f, base64_rep)
        return base64_rep.getvalue()

    # Look for the archive in the runtime properties.
    encoded_source = ctx.instance.runtime_properties.get('terraform_source')
    if not encoded_source:
        # Not found, so we need to prepare a ZIP file of the archive,
        # and then set it as a runtime property for future operations.
        terraform_source = _resource_config['source']
        split = terraform_source.split('://')
        schema = split[0]
        if schema in ['http', 'https']:
            ctx.logger.info("Downloading template from %s", terraform_source)
            with requests.get(terraform_source, allow_redirects=True,
                              stream=True) as response:
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(
                        suffix=".zip", delete=False) as source_temp:
                    terraform_source_zip = source_temp.name
                    for chunk in response.iter_content(chunk_size=None):
                        source_temp.write(chunk)
            ctx.logger.info("Template downloaded successfully")
        else:
            if os.path.isabs(terraform_source):
                dst = "/tmp/terraform_{0}.zip".format(int(round(time.time() * 1000)))
                shutil.copy(terraform_source, dst)
                terraform_source_zip = dst
            else:
                terraform_source_zip = ctx.download_resource(terraform_source)


        # By getting here, "terraform_source_zip" is the path to a ZIP
        # file containing the Terraform files.
        # We need to encode the contents of the file and set them
        # as a runtime property.
        base64_rep = _file_to_base64(terraform_source_zip)
        ctx.instance.runtime_properties['terraform_source'] = base64_rep
        ctx.instance.runtime_properties['last_source_location'] = terraform_source
    else:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            base64.decode(StringIO.StringIO(encoded_source), f)
            terraform_source_zip = f.name

    # By getting here, "terraform_source_zip" is the path to a ZIP file containing
    # the Terraform files.
    storage_path = ctx.node.properties['storage_path'] or None
    if storage_path and not os.path.isdir(storage_path):
        os.makedirs(storage_path)
    extracted_source = unzip_archive(ctx, terraform_source_zip, storage_path)
    os.remove(terraform_source_zip)

    backend = _resource_config.get('backend')
    if backend:
        backend_string = create_backend_string(
            backend['name'], backend.get('options', {}))
        backend_file_path = os.path.join(
            extracted_source, '{0}.tf'.format(backend['name']))
        with open(backend_file_path, 'w') as infile:
            infile.write(backend_string)

    ctx.logger.debug("Extracted Terraform files: %s", extracted_source)
    try:
        yield extracted_source
    finally:
        ctx.logger.debug("Re-packaging Terraform files from %s", extracted_source)
        with tempfile.NamedTemporaryFile(suffix=".zip",
                                         delete=False) as updated_zip:
            updated_zip.close()
            with zipfile.ZipFile(
                    updated_zip.name, mode='w',
                    compression=zipfile.ZIP_DEFLATED) as output_file:
                for dir_name, subdirs, filenames in os.walk(extracted_source):
                    for filename in filenames:
                        file_to_add = os.path.join(dir_name, filename)
                        arc_name = file_to_add[len(extracted_source)+1:]
                        ctx.logger.debug("Adding: %s as %s", file_to_add, arc_name)
                        output_file.write(file_to_add, arcname=arc_name)

        base64_rep = _file_to_base64(updated_zip.name)
        ctx.instance.runtime_properties['terraform_source'] = base64_rep
        os.remove(updated_zip.name)
        shutil.rmtree(extracted_source)


def create_backend_string(name, options):
    # TODO: Get a better way of setting backends.
    option_string = ''
    for option_name, option_value in options.items():
        if isinstance(option_value, basestring):
            option_value = '"%s"' % option_value
        option_string += '    %s = %s\n' % (option_name, option_value)
    backend_block = TERRAFORM_BACKEND % (name, option_string)
    return 'terraform {\n%s\n}' % backend_block


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
        self.logger.info("%s%s", self.prefix, line.rstrip('\n'))


class CapturingOutputConsumer(OutputConsumer):
    def __init__(self, out):
        OutputConsumer.__init__(self, out)
        self.buffer = StringIO.StringIO()
        self.consumer.start()

    def handle_line(self, line):
        self.buffer.write(line)

    def get_buffer(self):
        return self.buffer
