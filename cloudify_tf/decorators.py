from functools import wraps

from .terraform import Terraform
from .utils import (is_using_existing,
                    get_terraform_source)


def with_terraform(func):
    """Read the terraform source, dump it in the working directory (where
        terraform executable is called), and store the state for later dumping.

    This wrapper is the entry point for the following process:
    1. Call the get_terraform_source, which is the Terraform Template
        "main.tf", for example. This can be stored in runtime properties or
        gathered from a URL or as a resource in a blueprint.
    2. Check for the terraform source in runtime properties or in node
        properties via "get_terraform_source_material".
    3. Update the retrieved source in the runtime properties using
        update_terraform_source_material.
    4. Dump the terraform source in the node template working directory
        in the deployment directory using _yield_terraform_source.
    5. This location is passed to Terraform.from_ctx as the terraform_source
        variable below.
    6. Create the Terraform interface "tf", which then gets executed as
        tf.apply() or tf.destroy(), etc.

    :param func:
    :return:
    """

    @wraps(func)
    def f(*args, **kwargs):
        ctx = kwargs['ctx']
        if ctx.workflow_id == 'update' and not is_using_existing(target=False):
            ctx.logger.error(
                'The node type cloudify.nodes.terraform, which governs the '
                'Terraform binary installation method is not currently '
                'supported by deployment update. Deployment update rolls back '
                'changed nodes, deleting the deployment directory in the '
                'process. If only the cloudify.nodes.terraform.Module is '
                'changed, then the Terraform binary may not be present in '
                'the manager filesystem. This will result in corruption of '
                'the Cloudify deployment. Create a new deployment with the '
                'cloudify.nodes.terraform configured for local binary use. '
                'You can do this by setting '
                'terraform_config.use_external_resource to True, and '
                'terraform_config.executable_path to the path of an '
                'existing Terraform binary on the Cloudify manager file '
                'system. If necessary, contact your administrator about '
                'uploading Terraform binaries to the Cloudify manager.')
            return
        with get_terraform_source() as terraform_source:
            tf = Terraform.from_ctx(ctx, terraform_source)
            kwargs['tf'] = tf
            return func(*args, **kwargs)
    return f


def skip_if_existing(func):
    @wraps(func)
    def f(*args, **kwargs):
        if not is_using_existing():
            return func(*args, **kwargs)
    return f
