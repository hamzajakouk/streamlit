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

import time

from streamlit.elements.spinner import spinner
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.runtime.scriptrunner import get_script_run_ctx


def post_parent_message(message: str) -> str:
    """
    Send a string message to the parent window.
    """
    with spinner("Sending message..."):
        ctx = get_script_run_ctx()
        post_msg = ForwardMsg()
        post_msg.parent_message.message = message
        ctx.enqueue(post_msg)
        time.sleep(2)

    return message
