def _terraform_operation(ctx, operation, node_ids, node_instance_ids):
    graph = ctx.graph_mode()
    sequence = graph.sequence()
    # Iterate over all node instances of type "cloudify.nodes.terraform.Module"
    # and refresh states.
    for node_instance in ctx.node_instances:
        if node_ids and (node_instance.node.id not in node_ids):
            continue
        if node_instance_ids and (node_instance.id not in node_instance_ids):
            continue
        if 'cloudify.nodes.terraform.Module' in node_instance.node.type_hierarchy:
            ctx.logger.info("Adding node instance: %s", node_instance.id)
            sequence.add(node_instance.execute_operation(operation))
    return graph


def refresh_resources(ctx, node_ids, node_instance_ids):
    _terraform_operation(ctx, "terraform.refresh", node_ids, node_instance_ids).execute()


def apply_resources(ctx, node_ids, node_instance_ids):
    _terraform_operation(ctx, "terraform.apply", node_ids, node_instance_ids).execute()
