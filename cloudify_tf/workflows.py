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


def _terraform_operation(ctx, operation, node_ids,
                         node_instance_ids, **kwargs):
    graph = ctx.graph_mode()
    sequence = graph.sequence()
    # Iterate over all node instances of type "cloudify.nodes.terraform.Module"
    # and refresh states.
    for node_instance in ctx.node_instances:
        if node_ids and (node_instance.node.id not in node_ids):
            continue
        if node_instance_ids and (node_instance.id not in node_instance_ids):
            continue
        if 'cloudify.nodes.terraform.Module' in \
                node_instance.node.type_hierarchy:
            ctx.logger.info("Adding node instance: %s", node_instance.id)
            sequence.add(
                node_instance.execute_operation(
                    operation,
                    kwargs=kwargs,
                    allow_kwargs_override=True)
            )

    return graph


def refresh_resources(ctx, node_ids, node_instance_ids):
    _terraform_operation(
        ctx,
        "terraform.refresh",
        node_ids,
        node_instance_ids).execute()


def reload_resources(ctx, node_ids, node_instance_ids,
                     source, destroy_previous):
    kwargs = dict(destroy_previous=destroy_previous)
    if source:
        kwargs['source'] = source
    _terraform_operation(
        ctx,
        "terraform.reload",
        node_ids,
        node_instance_ids,
        **kwargs).execute()
