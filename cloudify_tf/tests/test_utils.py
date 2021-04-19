# Copyright (c) 2021 Cloudify Platform Ltd. All rights reserved
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

from cloudify.state import current_ctx

from . import TestBase
from ..utils import refresh_resources_drifts_properties
from ..constants import DRIFTS, IS_DRIFTED


class TestUtils(TestBase):
    def setUp(self):
        super(TestUtils, self).setUp()
        self.resource_name = "example_vpc"
        self.vpc_change = {"actions": ["no-op"],
                           "before": {
                               "arn":
                                   "fake_arn",

                               "cidr_block":
                                   "10.10.0.0/16",
                           },
                           "after": {
                               "arn":
                                   "fake_arn",
                               "cidr_block":
                                   "10.10.0.0/16",
                           },
                           "after_unknown": {}}
        self.fake_plan_json = {"format_version": "0.1",
                               "terraform_version": "0.13.4",
                               "variables": {},
                               "planned_values": {},
                               "resource_changes": [
                                   {"address": "aws_vpc.example_vpc",
                                    "mode": "managed",
                                    "type": "aws_vpc",
                                    "name": self.resource_name,
                                    "provider_name":
                                        "registry.terraform.io/hashicorp/aws",
                                    "change": self.vpc_change}],
                               "prior_state": {},
                               "configuration": {}}

    def test_refresh_resources_drifts_properties_no_drifts(self):
        self.fake_plan_json["resource_changes"] = []
        ctx = self.mock_ctx("test_no_op_drifts", None)
        current_ctx.set(ctx=ctx)
        refresh_resources_drifts_properties(self.fake_plan_json)
        self.assertEqual(ctx.instance.runtime_properties[DRIFTS], {})
        self.assertEqual(ctx.instance.runtime_properties[IS_DRIFTED], False)

    def test_refresh_resources_drifts_properties_no_op_drifts(self):
        ctx = self.mock_ctx("test_no_op_drifts", None)
        current_ctx.set(ctx=ctx)
        refresh_resources_drifts_properties(self.fake_plan_json)
        self.assertEqual(ctx.instance.runtime_properties[DRIFTS], {})
        self.assertEqual(ctx.instance.runtime_properties[IS_DRIFTED], False)

    def test_refresh_resources_drifts_properties_with_drifts(self):
        ctx = self.mock_ctx("test_no_op_drifts", None)
        current_ctx.set(ctx=ctx)
        # Change the operation needed just to check we store the changes
        self.vpc_change["actions"] = ["update"]
        refresh_resources_drifts_properties(self.fake_plan_json)
        self.assertEqual(ctx.instance.runtime_properties[IS_DRIFTED], True)
        self.assertDictEqual(ctx.instance.runtime_properties[DRIFTS],
                             {self.resource_name: self.vpc_change})
