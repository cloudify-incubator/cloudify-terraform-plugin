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
from mock import (patch, Mock)
from uuid import uuid1
from tempfile import mkdtemp

from cloudify.state import current_ctx
from cloudify.mocks import (MockContext, MockCloudifyContext,
                            MockNodeInstanceContext,
                            MockNodeContext)

from ..tasks import (install,
                     apply,
                     set_directory_config)
from ..utils import RELATIONSHIP_INSTANCE


test_dir1 = mkdtemp()
test_dir2 = mkdtemp()
test_dir3 = mkdtemp()


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

    def get_terraform_conf_props(self, module_root):
        return {
            "terraform_config": {
                "executable_path": path.join(module_root, "terraform"),
                "storage_path": module_root,
                "plugins_dir": path.join(
                    module_root, '.terraform', "plugins"),
            },
            "resource_config": {
                "use_existing_resource": False,
                "installation_source":
                    "https://releases.hashicorp.com/terraform/0.11.7/"
                    "terraform_0.11.7_linux_amd64.zip",
                "plugins": {}
            }
        }

    def get_terraform_module_conf_props(self, module_root):
        return {
            "resource_config": {
                "source": {
                    "location": path.join(module_root, "template"),
                },
                "variables": {
                    "a": "var1",
                    "b": "var2"
                },
                "environment_variables": {
                    "EXEC_PATH": path.join(module_root, "execution"),
                }
            }
        }

    @patch('cloudify_tf.utils.get_node_instance_dir', return_value=test_dir1)
    def test_install(self, _):
        conf = self.get_terraform_conf_props(test_dir1)
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
        target = MockContext({
            'instance': MockNodeInstanceContext(
                id='terra_install-1',
                runtime_properties=self.get_terraform_conf_props(
                    test_dir2).get("terraform_config")
            ),
            'node': MockNodeContext(
                id='1',
                properties=self.get_terraform_conf_props(test_dir2)
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
                properties=self.get_terraform_module_conf_props(
                    source_work_dir)
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

    @patch('cloudify_tf.utils.get_node_instance_dir', return_value=test_dir3)
    def test_apply_no_output(self, *_):
        conf = self.get_terraform_module_conf_props(test_dir3)
        ctx = self.mock_ctx("test_apply_no_output", conf)
        current_ctx.set(ctx=ctx)
        kwargs = {
            'ctx': ctx
        }

        tf_pulled_resources = {'resources': [{'name': 'eip',
                                              'value': '10.0.0.1'}]}
        tf_output = {}
        mock_tf_apply = Mock()
        mock_tf_apply.init.return_value = 'terraform initialized folder'
        mock_tf_apply.plan.return_value = 'terraform plan'
        mock_tf_apply.apply.return_value = 'terraform executing'
        mock_tf_apply.state_pull.return_value = tf_pulled_resources
        mock_tf_apply.output.return_value = tf_output

        with patch('cloudify_tf.terraform.Terraform.from_ctx',
                   return_value=mock_tf_apply):
            apply(**kwargs)
            self.assertTrue(mock_tf_apply.state_pull.called)
            self.assertEqual(ctx.instance.runtime_properties['resources'],
                             {'eip': tf_pulled_resources.get('resources')[0]})
            self.assertEqual(ctx.instance.runtime_properties['outputs'],
                             tf_output)

    @patch('cloudify_tf.utils.get_node_instance_dir', return_value=test_dir3)
    def test_apply_with_output(self, *_):
        conf = self.get_terraform_module_conf_props(test_dir3)
        ctx = self.mock_ctx("test_apply_with_output", conf)
        current_ctx.set(ctx=ctx)
        kwargs = {
            'ctx': ctx
        }

        tf_pulled_resources = {'resources': [{'name': 'eip',
                                              'value': '10.0.0.1'}]}
        tf_output = {'elastic_ip': '10.0.0.1'}
        mock_tf_apply = Mock()
        mock_tf_apply.init.return_value = 'terraform initialized folder'
        mock_tf_apply.plan.return_value = 'terraform plan'
        mock_tf_apply.apply.return_value = 'terraform executing'
        mock_tf_apply.state_pull.return_value = tf_pulled_resources
        mock_tf_apply.output.return_value = tf_output

        with patch('cloudify_tf.terraform.Terraform.from_ctx',
                   return_value=mock_tf_apply):
            apply(**kwargs)
            self.assertTrue(mock_tf_apply.state_pull.called)
            self.assertEqual(ctx.instance.runtime_properties['resources'],
                             {'eip': tf_pulled_resources.get('resources')[0]})
            self.assertEqual(ctx.instance.runtime_properties['outputs'],
                             tf_output)
