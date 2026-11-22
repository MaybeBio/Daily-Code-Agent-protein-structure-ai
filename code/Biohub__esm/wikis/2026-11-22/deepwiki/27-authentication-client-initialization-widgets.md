# Authentication & Client Initialization Widgets

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/widgets/utils/clients.py](esm/widgets/utils/clients.py)
- [esm/widgets/utils/types.py](esm/widgets/utils/types.py)
- [esm/widgets/views/esm3_generation_launcher.py](esm/widgets/views/esm3_generation_launcher.py)
- [esm/widgets/views/login.py](esm/widgets/views/login.py)
- [esm/widgets/views/prediction.py](esm/widgets/views/prediction.py)

</details>



This page documents the interactive components within `esm.widgets` responsible for managing user authentication and initializing inference clients. These widgets provide a user-friendly interface for choosing between local execution and remote Biohub Platform (Forge) services, handling API key management, and configuring the underlying SDK clients.

## Overview of Initialization Flow

The initialization process follows a structured path from user selection to the instantiation of a functional `ESM3InferenceClient`. The system uses a container pattern to bridge the gap between interactive Jupyter widgets and subsequent notebook code cells.

### Data Flow Diagram: Client Initialization

This diagram illustrates the flow from the Natural Language Space (UI selection) to the Code Entity Space (Client objects).

```mermaid
graph TD
    subgraph "Natural Language Space (UI)"
        "UI_Selection[Select Inference Option]" --> "Forge_Option[Forge/Biohub Platform API]"
        "UI_Selection" --> "Local_Option[Local]"
        "Forge_Option" --> "Token_Input[Enter API Token]"
        "Local_Option" --> "Model_Fixed[esm3-sm-open-v1]"
    end

    subgraph "Code Entity Space (esm.widgets)"
        "create_login_ui[create_login_ui]" -- "manages" --> "ClientInitContainer[ClientInitContainer]"
        "ClientInitContainer" -- "calls" --> "get_forge_client[get_forge_client]"
        "ClientInitContainer" -- "calls" --> "get_local_client[get_local_client]"
    end

    subgraph "SDK Implementation (esm.sdk)"
        "get_forge_client" --> "ESM3ForgeInferenceClient[ESM3ForgeInferenceClient]"
        "get_local_client" --> "ESM3[ESM3 (Local PyTorch Model)]"
    end

    "Token_Input" -.-> "ESM_API_KEY[os.environ['ESM_API_KEY']]"
    "ESM_API_KEY" -.-> "get_forge_client"
```

**Sources:** [esm/widgets/views/login.py:11-170](), [esm/widgets/utils/clients.py:12-28](), [esm/widgets/utils/types.py:8-8]()

---

## Key Components

### ClientInitContainer
The `ClientInitContainer` is a metadata and callback wrapper defined in `esm.widgets.utils.types`. It acts as a bridge between the widget UI and the notebook's execution environment.
*   **`metadata`**: A dictionary storing user selections, such as the chosen `inference_option` [esm/widgets/views/login.py:117-117]().
*   **`client_init_callback`**: A `partial` function that, when called, returns a fully initialized `ESM3InferenceClient` [esm/widgets/views/login.py:144-148]().

### create_login_ui
The primary entry point for authentication is `create_login_ui` [esm/widgets/views/login.py:11-170](). This function constructs an `ipywidgets.VBox` containing:
1.  **Backend Selector**: A `RadioButtons` widget allowing users to toggle between "Forge/Biohub Platform API" and "Local" [esm/widgets/views/login.py:33-38]().
2.  **API Key Management**: For Forge users, it provides a text input for the `ESM_API_KEY`. It supports setting this key as an environment variable directly from the UI [esm/widgets/views/login.py:109-110]().
3.  **Model Selection**:
    *   **Forge**: Allows entering a specific model name (defaulting to `esm3-open`) [esm/widgets/views/login.py:91-96]().
    *   **Local**: Hardcoded to `esm3-sm-open-v1` as it is the primary open-source model supported for local inference [esm/widgets/views/login.py:85-90]().

**Sources:** [esm/widgets/views/login.py:11-170](), [esm/widgets/utils/types.py:8-8]()

---

## Client Initialization Callbacks

The widgets use utility functions in `esm/widgets/utils/clients.py` to instantiate the appropriate client type based on the UI state.

### get_forge_client
This function initializes a remote client for the Biohub Platform.
*   **Implementation**: It retrieves the `ESM_API_KEY` from environment variables [esm/widgets/utils/clients.py:21-21]().
*   **Return Type**: Returns an instance of `ESM3ForgeInferenceClient` configured with the specified model name and the Biohub API URL (`https://biohub.ai`) [esm/widgets/utils/clients.py:26-28]().

### get_local_client
This function initializes a local instance of the ESM3 model.
*   **Implementation**: It first validates that the user is logged into Hugging Face via `huggingface_hub.whoami()` [esm/widgets/utils/clients.py:13-17]().
*   **Return Type**: Returns a local `ESM3` model instance loaded onto the GPU (`cuda`) using the `from_pretrained` factory method [esm/widgets/utils/clients.py:17-17]().

### Logic Flow: Callback Assignment
When the user clicks the "Start using ESM3" button in the login UI, the `on_start` callback is triggered [esm/widgets/views/login.py:142-162]():

| Selected Option | Callback Assigned | Target Client Class |
| :--- | :--- | :--- |
| **Forge/Biohub** | `partial(get_forge_client, forge_model.value)` | `ESM3ForgeInferenceClient` |
| **Local** | `partial(get_local_client)` | `ESM3` (local model) |

**Sources:** [esm/widgets/utils/clients.py:12-28](), [esm/widgets/views/login.py:142-162]()

---

## Widget Interaction & UI State

The login UI dynamically updates based on user interaction via the `on_selection_change` observer [esm/widgets/views/login.py:116-140]().

### UI State Transitions

```mermaid
graph LR
    subgraph "Selection Change [on_selection_change]"
        "Init[Initial State]" -- "Select Forge" --> "Forge_UI[Show Token Input + Forge Model]"
        "Init" -- "Select Local" --> "Local_UI[Show Fixed Local Model]"
    end

    subgraph "Authentication [on_forge_login_clicked]"
        "Forge_UI" -- "Input Token" --> "Env_Var[Set ESM_API_KEY]"
        "Env_Var" --> "Logged_In_View[Show Success Message]"
    end
```

### Implementation Details:
*   **Environment Variable Sync**: When `forge_set_as_env` is checked, the token entered in `forge_token_input` is written to `os.environ["ESM_API_KEY"]` [esm/widgets/views/login.py:109-110]().
*   **Persistence**: The UI checks for the existence of `ESM_API_KEY` in the environment upon initialization to determine whether to show the login form or the "already logged in" view [esm/widgets/views/login.py:77-81]().

**Sources:** [esm/widgets/views/login.py:47-82](), [esm/widgets/views/login.py:107-140]()

---