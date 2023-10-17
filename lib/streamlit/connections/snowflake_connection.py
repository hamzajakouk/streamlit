# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# NOTE: We won't always be able to import from snowflake.{connector, snowpark}.* so need
# the `type: ignore` comment below, but that comment will explode if `warn-unused-ignores`
# is turned on when the package is available. Unfortunately, mypy doesn't provide a good
# way to configure this at a per-line level :(
# mypy: no-warn-unused-ignores

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pandas as pd

from streamlit.connections import BaseConnection
from streamlit.connections.util import running_in_sis
from streamlit.errors import StreamlitAPIException
from streamlit.runtime.caching import cache_data

if TYPE_CHECKING:
    from snowflake.connector import (  # type:ignore[import] # isort: skip
        SnowflakeConnection as InternalSnowflakeConnection,
    )
    from snowflake.connector.cursor import SnowflakeCursor  # type:ignore[import]
    from snowflake.snowpark.session import Session  # type:ignore[import]


_REQUIRED_CONNECTION_PARAMS = {"account"}


class SnowflakeConnection(BaseConnection["InternalSnowflakeConnection"]):
    """A connection to Snowflake using the Snowflake Python Connector. Initialize using
    ``st.connection("<name>", type="snowflake")``.

    SnowflakeConnection supports direct SQL querying using ``.query("...")``, access to
    the underlying Snowflake Python Connector object with ``.raw_connection``, and other
    convenience functions. See the methods below for more information.
    SnowflakeConnections should always be created using ``st.connection()``, **not**
    initialized directly.
    """

    def _connect(self, **kwargs) -> "InternalSnowflakeConnection":
        import snowflake.connector  # type:ignore[import]
        from snowflake.snowpark.context import get_active_session  # type:ignore[import]

        # If we're running in SiS, just call get_active_session() and retrieve the
        # lower-level connection from it.
        if running_in_sis():
            session = get_active_session()

            if hasattr(session, "connection"):
                return session.connection
            # session.connection is only a valid attr in more recent versions of
            # snowflake-connector-python, so we fall back to grabbing
            # session._conn._conn if `.connection` is unavailable.
            return session._conn._conn

        # We require qmark-style parameters everywhere for consistency across different
        # environments where SnowflakeConnections may be used.
        snowflake.connector.paramstyle = "qmark"

        # Otherwise, attempt to create a new connection from whatever credentials we
        # have available.
        st_secrets = self._secrets.to_dict()
        if len(st_secrets):
            conn_kwargs = {**st_secrets, **kwargs}
            return snowflake.connector.connect(**conn_kwargs)

        # session.connector.connection.CONFIG_MANAGER is only available in more recent
        # versions of snowflake-connector-python.
        if hasattr(snowflake.connector.connection, "CONFIG_MANAGER"):
            config_mgr = snowflake.connector.connection.CONFIG_MANAGER

            default_connection_name = "default"
            try:
                default_connection_name = config_mgr["default_connection_name"]
            except snowflake.connector.errors.ConfigSourceError:
                # Similarly, config_mgr["default_connection_name"] only exists in even
                # later versions of recent versions. if it doesn't, we just use
                # "default" as the default connection name.
                pass

            connection_name = (
                default_connection_name
                if self._connection_name == "snowflake"
                else self._connection_name
            )
            return snowflake.connector.connect(
                connection_name=connection_name,
                **kwargs,
            )

        return snowflake.connector.connect(**kwargs)

    def query(
        self,
        sql: str,
        *,  # keyword-only arguments:
        ttl: float | int | timedelta | None = None,
        show_spinner: bool | str = "Running `snowflake.query(...)`.",
        params=None,
        **kwargs,
    ) -> pd.DataFrame:
        """Run a read-only SQL query.

        This method implements both query result caching (with caching behavior
        identical to that of using ``@st.cache_data``) as well as simple error handling/retries.

        .. note::
            Queries that are run without a specified ttl are cached indefinitely.

        Parameters
        ----------
        sql : str
            The read-only SQL query to execute.
        ttl : float, int, timedelta or None
            The maximum number of seconds to keep results in the cache, or
            None if cached results should not expire. The default is None.
        show_spinner : boolean or string
            Enable the spinner. The default is to show a spinner when there is a
            "cache miss" and the cached resource is being created. If a string, the value
            of the show_spinner param will be used for the spinner text.
        params : list, tuple, dict or None
            List of parameters to pass to the execute method. The syntax used to pass
            parameters is database driver dependent. Check your database driver
            documentation for which of the five syntax styles, described in `PEP 249
            paramstyle <https://peps.python.org/pep-0249/#paramstyle>`_, is supported.
            Default is None.

        Returns
        -------
        pd.DataFrame
            The result of running the query, formatted as a pandas DataFrame.

        Example
        -------
        >>> import streamlit as st
        >>>
        >>> conn = st.connection("snowflake")
        >>> df = conn.query("select * from pet_owners")
        >>> st.dataframe(df)
        """
        from snowflake.connector import Error as SnowflakeError
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_fixed,
        )

        @retry(
            after=lambda _: self.reset(),
            stop=stop_after_attempt(3),
            reraise=True,
            retry=retry_if_exception_type(SnowflakeError),
            wait=wait_fixed(1),
        )
        @cache_data(
            show_spinner=show_spinner,
            ttl=ttl,
        )
        def _query(sql: str) -> pd.DataFrame:
            cur = self._instance.cursor()
            cur.execute(sql, params=params, **kwargs)
            return cur.fetch_pandas_all()

        return _query(sql)

    def write_pandas(
        self,
        df: pd.DataFrame,
        table_name: str,
        database: str | None = None,
        schema: str | None = None,
        chunk_size: int | None = None,
        **kwargs,
    ) -> tuple[bool, int, int]:
        """Call snowflake.connector.pandas_tools.write_pandas with this connection.

        This convenience method is simply a thin wrapper around the ``write_pandas``
        function of the same name from ``snowflake.connector.pandas_tools``. For more
        information, see the `Snowflake Python Connector documentation
        <https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api#write_pandas>`_.
        """
        from snowflake.connector.pandas_tools import write_pandas  # type:ignore[import]

        success, nchunks, nrows, _ = write_pandas(
            conn=self._instance,
            df=df,
            table_name=table_name,
            database=database,
            schema=schema,
            chunk_size=chunk_size,
            **kwargs,
        )

        return (success, nchunks, nrows)

    def cursor(self) -> "SnowflakeCursor":
        """Return a PEP 249-compliant cursor object.

        For more information, see the `Snowflake Python Connector documentation
        <https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api#object-cursor>`_.
        """
        return self._instance.cursor()

    @property
    def raw_connection(self) -> "InternalSnowflakeConnection":
        """Access the underlying Snowflake Python connector object.

        Information on how to use the Snowflake Python Connector can be found in the
        `Snowflake Python Connector documentation<https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-example>`_.
        """
        return self._instance

    def session(self) -> "Session":
        """Create a new Snowpark Session from this connection.

        Information on how to use Snowpark sessions can be found in the `Snowpark documentation
        <https://docs.snowflake.com/en/developer-guide/snowpark/python/working-with-dataframes>`_.
        """
        from snowflake.snowpark.context import get_active_session  # type:ignore[import]
        from snowflake.snowpark.session import Session  # type:ignore[import]

        if running_in_sis():
            return get_active_session()

        return cast(
            Session, Session.builder.configs({"connection": self._instance}).create()
        )
