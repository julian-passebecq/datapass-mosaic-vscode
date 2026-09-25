"""Snowflake SQL dialect translated to DuckDB for a documented subset (Practice `snowflake` language). Not Snowflake."""
from .translate import FUNCTIONS, LABEL, SnowflakeDialectError, Translation, translate

__all__ = ['FUNCTIONS', 'LABEL', 'SnowflakeDialectError', 'Translation', 'translate']
