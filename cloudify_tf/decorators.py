from functools import wraps

from .terraform import Terraform
from .utils import (is_using_existing,
                    get_terraform_source)


def with_terraform(func):
    @wraps(func)
    def f(*args, **kwargs):
        ctx = kwargs['ctx']
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
