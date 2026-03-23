import os
import types
import typing
from ruamel.yaml import YAML
from pydantic import BaseModel, TypeAdapter, ValidationError
from vtes_scraper.models import Tournament

yaml = YAML()


def _inner_model(annotation) -> type[BaseModel] | None:
    """Return the BaseModel subclass for an annotation, unwrapping list/Optional."""
    origin = typing.get_origin(annotation)
    if origin is list:
        args = typing.get_args(annotation)
        return _inner_model(args[0]) if args else None
    if origin is typing.Union or isinstance(annotation, types.UnionType):
        for arg in typing.get_args(annotation):
            if arg is not type(None):
                result = _inner_model(arg)
                if result is not None:
                    return result
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _walk(data: dict, model_class: type[BaseModel]) -> None:
    """Walk YAML data in-place, coercing values to their model field types."""
    for field_name, field_info in model_class.model_fields.items():
        if field_name not in data:
            continue
        value = data[field_name]
        annotation = field_info.annotation
        origin = typing.get_origin(annotation)
        nested_model = _inner_model(annotation)

        if origin is list and nested_model is not None:
            # list[SomeModel] → recurse into each item
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _walk(item, nested_model)
        elif origin is not list and nested_model is not None:
            # SomeModel or Optional[SomeModel] → recurse
            if isinstance(value, dict):
                _walk(value, nested_model)
        else:
            # Scalar field → validate and coerce if needed
            coerced = TypeAdapter(annotation).validate_python(value)
            if coerced != value:
                data[field_name] = coerced


def update_yaml_files(base_dir: str) -> None:
    for root, _, files in os.walk(base_dir):
        for file in files:
            if not file.endswith(".yaml"):
                continue
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.load(f)
                _walk(data, Tournament)
                with open(file_path, "w", encoding="utf-8") as f:
                    yaml.dump(data, f)
                print(f"Updated: {file_path}")
            except ValidationError as e:
                print(f"Validation error in {file_path}: {e}")
            except Exception as e:
                print(f"Error processing {file_path}: {e}")


if __name__ == "__main__":
    update_yaml_files("twds")
