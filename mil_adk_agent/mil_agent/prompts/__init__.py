import os

from jinja2 import Environment, FileSystemLoader

# Set up Jinja2 environment for templates directory
TEMPLATES_FOLDER_NAME = "templates"
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), TEMPLATES_FOLDER_NAME)
prompt_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


class Prompt:
    def __init__(self, template_path: str):
        try:
            self.template = prompt_env.get_template(template_path)
        except Exception as e:
            raise RuntimeError(f"Error loading template '{template_path}': {e}")

    def render(self, context: dict | None = None) -> str:
        try:
            return self.template.render(**(context or {}))
        except Exception as e:
            raise RuntimeError(f"Error rendering template: {e}")
