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
import json
import tempfile

from contextlib import contextmanager

from cloudify.exceptions import NonRecoverableError

from ..utils import (
    run_subprocess,
    get_plugins_dir,
    get_executable_path,
    get_resource_config)


class Terraform(object):
    # TODO: Rework this to put the execute method in its own module.
    # TODO: After you do that, move all the SSH commands to the tasks module.

    def __init__(self,
                 logger,
                 binary_path,
                 plugins_dir,
                 root_module,
                 variables=None,
                 environment_variables=None):

        self.binary_path = binary_path
        self.plugins_dir = self.set_plugins_dir(plugins_dir)
        self.root_module = root_module
        self.logger = logger

        if not isinstance(environment_variables, dict):
            raise Exception(
                "Unexpected type for environment variables (should be a "
                "dict): {0}".format(type(
                    environment_variables)))

        if not isinstance(variables, dict):
            raise Exception(
                "Unexpected type for variables (should be a "
                "dict): {0}".format(type(
                    variables)))

        self.env = environment_variables
        self.variables = variables

    @staticmethod
    def set_plugins_dir(path):
        if not os.listdir(path):
            return
        return path

    def execute(self, command, return_output=False):
        return run_subprocess(
            command, self.logger, self.root_module,
            self.env, return_output=return_output)

    def _tf_command(self, args):
        cmd = [self.binary_path]
        cmd.extend(args)
        return cmd

    @contextmanager
    def _vars_file(self, command):
        with tempfile.NamedTemporaryFile(suffix=".json",
                                         delete=False,
                                         mode="w",
                                         dir=self.root_module) as f:
            json.dump(self.variables, f)
            f.close()
            command.extend(['-var-file', f.name])
            yield
        os.remove(f.name)

    def version(self):
        return self.execute(self._tf_command(['version']), True)

    def init(self, additional_args=None):
        cmdline = ['init', '-no-color']
        if self.plugins_dir:
            cmdline.append('--plugin-dir=%s' % self.plugins_dir)
        command = self._tf_command(cmdline)
        if additional_args:
            command.extend(additional_args)
        return self.execute(command)

    def destroy(self):
        command = self._tf_command(['destroy', '-auto-approve', '-no-color'])
        with self._vars_file(command):
            return self.execute(command)

    def plan(self):
        command = self._tf_command(['plan', '-no-color'])
        with self._vars_file(command):
            return self.execute(command)

    def apply(self):
        command = self._tf_command(['apply', '-auto-approve', '-no-color'])
        with self._vars_file(command):
            return self.execute(command)

    def graph(self):
        command = self._tf_command(['graph'])
        return self.execute(command)

    def state_pull(self):
        command = self._tf_command(['state', 'pull'])
        pulled_state = self.execute(command, True)
        # If we got here, then the "state pull" return code must
        # be zero, and pulled_state actually contains a parse-able
        # JSON.
        if pulled_state:
            return json.loads(pulled_state)

    def refresh(self):
        command = self._tf_command(['refresh', '-no-color'])
        with self._vars_file(command):
            return self.execute(command)

    @staticmethod
    def from_ctx(ctx, terraform_source):
        executable_path = get_executable_path()
        plugins_dir = get_plugins_dir()
        resource_config = get_resource_config()
        if not os.path.exists(executable_path):
            raise NonRecoverableError(
                "Terraform's executable not found in {0}. Please set the "
                "'executable_path' property accordingly.".format(
                    executable_path))
        env_variables = resource_config.get('environment_variables')
        tf = Terraform(
                ctx.logger,
                executable_path,
                plugins_dir,
                terraform_source,
                variables=resource_config.get('variables'),
                environment_variables=env_variables)
        return tf
