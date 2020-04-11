**This project is under development** 

# Cloudify Terraform Plugin

This plugin provides the following functionality:

* Installation, configuration and uninstallation of Terraform itself
    * Terraform executable
    * Terraform providers and plugins
* Representation of Terraform modules as Cloudify nodes
* Refreshing Terraform state from the cloud
* Updating Terraform state and applying differences on the cloud

## Prerequisites

The Terraform plugin can work with a pre-existing Terraform installation, or it can create a Terraform
installation for you. In order to use a pre-existing Terraform installation, you will need to provide
the relevant paths when defining the Terraform node templates (see below).

## Module Source Specification

When defining a source for a Terraform URL, you can specify any of the following:

* URL to a Zip file
* URL to a `tar.gz` file
* Path to a Zip file
* Path to a `tar.gz` file
* URL to a Git repository (must end with `.git`)

## Node Types

Two node types are provided:

* `cloudify.nodes.terraform`: represents the Terraform installation
* `cloudify.nodes.terraform.Module`: represents a Terraform module

Refer to the documentation in [plugin.yaml](plugin.yaml) for more information about the node
types' properties.

### `cloudify.nodes.terraform.Module`

This node type represents a Terraform module. Its lifecycle consists of:

* `create`: initializes Terraform by calling `terraform init` and `terraform plan`.
* `configure`: executes `terraform state pull`
* `start`: executes `terraform apply`
* `delete`: executes `terraform destroy`

At the end of `start`, a runtime property by the name `resources` is being set on the node instance,
containing the exact dictionary provided by Terraform, representing the state.

In addition, certain day-two operations are provided:

* `terraform.reload`: reloads the template, either from its original location or from an alternative
  location.
* `terraform.refresh`: calls `terraform state pull`. 

The `resources` runtime property is updated after each of the aforementioned day-two operations.

## Workflows

The plugin provides the following workflows:

* `refresh_terraform_resources`: a simple wrapper for the `terraform.refresh` operation.
* `reload_terraform_template`: a simple wrapper for the `terraform.reload` operation.

These workflows, by default, call their relevant wrapped operation for all node instances of the
Terraform Module type in the current deployment.

If you have more than one Terraform modules in the same blueprint, you can narrow down the scope of the
workflows by specifying either the `node_instance_ids` or `node_ids` parameters to the workflows.

### Workflow Examples

```bash
cfy executions start refresh_terraform_resources -d dep_1
```

This will execute the "refresh" day-two operation on all node instances inside `dep_1` that represent Terraform
modules.

```bash
cfy executions start refresh_terraform_resources -d dep_1 -p node_ids=[tf_module_1]
```

This will execute the "refresh" day-two operation on all node instances that belong to the `tf_module_1` node
template.

## Blueprint Examples

For official blueprint examples using this Cloudify plugin, please see [Cloudify Community Blueprints Examples](https://github.com/cloudify-community/blueprint-examples/).

## To Do

  * Create a Terraform [Backend Service using HTTP Node Type](https://www.terraform.io/docs/backends/types/http.html).
    * Package in the plugin w/ a node type.
    * The service should run as a daemon.
    * Exposing Terraform resources via Terraform outputs should trigger `execute_resource` workflow on those resources.
    * This should enable a user to interact with Terraform and Cloudify from Terraform CLI.
  * Support Multiple Modules.
