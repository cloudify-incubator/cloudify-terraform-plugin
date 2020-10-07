########
# Copyright (c) 2014-2020 GigaSpaces Technologies Ltd. All rights reserved
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

import unittest
from os import path
from mock import patch
from uuid import uuid1
from tempfile import mkdtemp

from cloudify.state import current_ctx
from cloudify.mocks import (MockContext, MockCloudifyContext,
                            MockNodeInstanceContext,
                            MockNodeContext)

from ..tasks import (install,
                     set_directory_config)
from ..utils import RELATIONSHIP_INSTANCE


workdir = mkdtemp()


def get_tenant_name():
    return 'default_tenant'


def get_dir(*foo, **bar):
    return workdir


class MockCloudifyContextRels(MockCloudifyContext):

    @property
    def type(self):
        return RELATIONSHIP_INSTANCE


class TestPlugin(unittest.TestCase):

    def setUp(self):
        super(TestPlugin, self).setUp()

    def mock_ctx(self, test_name, test_properties,
                 test_runtime_properties=None):
        test_node_id = uuid1()
        ctx = MockCloudifyContext(
            node_id=test_node_id,
            properties=test_properties,
            runtime_properties=None if not test_runtime_properties
            else test_runtime_properties,
            deployment_id=test_name
        )
        return ctx

    @patch('cloudify_tf.utils._get_tenant_name', side_effect=get_tenant_name)
    @patch('cloudify_tf.utils.get_storage_path', side_effect=get_dir)
    @patch('cloudify_tf.tasks.get_deployment_dir', side_effect=get_dir)
    @patch('cloudify_tf.utils.get_deployment_dir', side_effect=get_dir)
    def test_install(self,
                     get_tenant_fn,
                     get_storage_path,
                     get_deployment_dir2,
                     get_deployment_dir):
        def get_terraform_conf_props():
            return {
                "terraform_config": {
                    "executable_path": path.join(workdir, "terraform"),
                    "storage_path": path.join(workdir, ".terraform"),
                    "plugins_dir": path.join(workdir, "plugins"),
                },
                "resource_config": {
                    "use_existing_resource": False,
                    "installation_source":
                        "https://releases.hashicorp.com/terraform/0.11.7/"
                        "terraform_0.11.7_linux_amd64.zip",
                    "plugins": []
                }
            }

        conf = get_terraform_conf_props()
        ctx = self.mock_ctx("test_install", conf)
        current_ctx.set(ctx=ctx)
        kwargs = {
            'ctx': ctx
        }
        install(**kwargs)
        self.assertEqual(ctx.instance.runtime_properties.get(
            "executable_path"),
                         conf.get("terraform_config").get("executable_path"))
        self.assertEqual(ctx.instance.runtime_properties.get("storage_path"),
                         conf.get("terraform_config").get("storage_path"))
        self.assertEqual(ctx.instance.runtime_properties.get("plugins_dir"),
                         conf.get("terraform_config").get("plugins_dir"))
        self.assertTrue(
            path.isfile(ctx.instance.runtime_properties.get(
                "executable_path")))

    @patch('cloudify_tf.utils._get_tenant_name', side_effect=get_tenant_name)
    @patch('cloudify_tf.utils.get_storage_path', side_effect=get_dir)
    @patch('cloudify_tf.utils.get_deployment_dir', side_effect=get_dir)
    def test_set_directory_config(self,
                                  get_tenant_fn,
                                  get_storage_path,
                                  get_deployment_dir):

        def get_terraform_conf_props():
            return {
                "terraform_config": {
                    "executable_path": path.join(workdir, "terraform"),
                    "storage_path": path.join(workdir, ".terraform"),
                    "plugins_dir": path.join(workdir, "plugins"),
                },
                "resource_config": {
                    "use_existing_resource": False,
                    "installation_source":
                        "https://releases.hashicorp.com/terraform/0.11.7/"
                        "terraform_0.11.7_linux_amd64.zip",
                    "plugins": []
                }
            }

        def get_terraform_module_conf_props():
            return {
                "resource_config": {
                    "source": path.join(workdir, "template"),
                    "variables": {
                        "a": "var1",
                        "b": "var2"
                    },
                    "environment_variables": {
                        "EXEC_PATH": path.join(workdir, "execution"),
                    }
                }
            }

        target = MockContext({
            'instance': MockNodeInstanceContext(
                id='terra_install-1',
                runtime_properties=get_terraform_conf_props().get(
                    "terraform_config")
            ),
            'node': MockNodeContext(
                id='1',
                properties=get_terraform_conf_props()
            ), '_context': {
                'node_id': '1'
            }})
        source = MockContext({
            'instance': MockNodeInstanceContext(
                id='terra_module-1',
                runtime_properties={}),
            'node': MockNodeContext(
                id='2',
                properties=get_terraform_module_conf_props()
            ), '_context': {
                'node_id': '2'
            }})
        ctx = MockCloudifyContextRels(source=source, target=target)
        current_ctx.set(ctx=ctx)
        kwargs = {
            'ctx': ctx
        }
        set_directory_config(**kwargs)
        self.assertEqual(
            ctx.source.instance.runtime_properties.get("executable_path"),
            ctx.target.instance.runtime_properties.get("executable_path"))
