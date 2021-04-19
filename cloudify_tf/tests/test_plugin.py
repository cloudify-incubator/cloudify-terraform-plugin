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

from os import path
from mock import patch
from tempfile import mkdtemp

from cloudify.state import current_ctx
from cloudify.mocks import (MockContext, MockCloudifyContext,
                            MockNodeInstanceContext,
                            MockNodeContext)

from . import TestBase
from ..tasks import (install,
                     set_directory_config)
from ..utils import RELATIONSHIP_INSTANCE


test_dir1 = mkdtemp()
test_dir2 = mkdtemp()


class MockCloudifyContextRels(MockCloudifyContext):

    @property
    def type(self):
        return RELATIONSHIP_INSTANCE


class TestPlugin(TestBase):

    def setUp(self):
        super(TestPlugin, self).setUp()

    @patch('cloudify_tf.utils.get_node_instance_dir', return_value=test_dir1)
    def test_install(self, _):
        def get_terraform_conf_props():
            return {
                "terraform_config": {
                    "executable_path": path.join(test_dir1, "terraform"),
                    "storage_path": test_dir1,
                    "plugins_dir": path.join(
                        test_dir1, '.terraform', "plugins"),
                },
                "resource_config": {
                    "use_existing_resource": False,
                    "installation_source":
                        "https://releases.hashicorp.com/terraform/0.11.7/"
                        "terraform_0.11.7_linux_amd64.zip",
                    "plugins": {}
                }
            }

        conf = get_terraform_conf_props()
        ctx = self.mock_ctx("test_install", conf)
        current_ctx.set(ctx=ctx)
        kwargs = {
            'ctx': ctx
        }
        install(**kwargs)
        self.assertEqual(
            ctx.instance.runtime_properties.get("executable_path"),
            conf.get("terraform_config").get("executable_path"))
        self.assertEqual(
            ctx.instance.runtime_properties.get("storage_path"),
            conf.get("terraform_config").get("storage_path"))
        self.assertEqual(
            ctx.instance.runtime_properties.get("plugins_dir"),
            conf.get("terraform_config").get("plugins_dir"))
        self.assertTrue(
            path.isfile(ctx.instance.runtime_properties.get(
                "executable_path")))

    @patch('cloudify_tf.utils.get_node_instance_dir', return_value=test_dir2)
    def test_set_directory_config(self, _):

        def get_terraform_conf_props(module_root=test_dir2):
            return {
                "terraform_config": {
                    "executable_path": path.join(module_root, "terraform"),
                    "storage_path": module_root,
                    "plugins_dir": path.join(module_root,
                                             '.terraform', "plugins"),
                },
                "resource_config": {
                    "use_existing_resource": False,
                    "installation_source":
                        "https://releases.hashicorp.com/terraform/0.11.7/"
                        "terraform_0.11.7_linux_amd64.zip",
                    "plugins": []
                }
            }

        def get_terraform_module_conf_props(module_root=test_dir2):
            return {
                "resource_config": {
                    "source": path.join(module_root, "template"),
                    "variables": {
                        "a": "var1",
                        "b": "var2"
                    },
                    "environment_variables": {
                        "EXEC_PATH": path.join(module_root, "execution"),
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
        source_work_dir = mkdtemp()
        source = MockContext({
            'instance': MockNodeInstanceContext(
                id='terra_module-1',
                runtime_properties={}),
            'node': MockNodeContext(
                id='2',
                properties=get_terraform_module_conf_props(source_work_dir)
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
