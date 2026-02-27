import dash
from dash import html, Output, Input
import dash_cytoscape as cyto

def network_ui(elements):
    app = dash.Dash(__name__)

    elements = [
        {'data': {'id': 'a', 'label': 'Node A'}},
        {'data': {'id': 'b', 'label': 'Node B'}},
        {
            'data': {'source': 'a', 'target': 'b', 'label': 'Edge A-B'},
            'classes': 'warning-edge'  # class name changed
        }
    ]

    app.layout = html.Div([
        cyto.Cytoscape(
            id='cytoscape-network',
            elements=elements,
            style={'width': '1000px', 'height': '800px'},
            stylesheet=[
                {'selector': 'node', 'style': {'content': 'data(label)'}},
                {'selector': 'edge', 'style': {'line-color': '#ccc', 'width': 2}},
                {
                    'selector': '.warning-edge',  # selector for your class
                    'style': {
                        'line-color': 'yellow',  # correct edge color property
                        'width': 4
                    }
                }
            ]
        ),
        html.Div(id='tooltip-div', style={'marginTop': '20px', 'fontWeight': 'bold'})
    ])

    @app.callback(
        Output('tooltip-div', 'children'),
        Input('cytoscape-network', 'mouseoverNodeData')
    )
    def display_tooltip(node_data):
        if node_data:
            return f"Hovered node: {node_data['label']} (ID: {node_data['id']})"
        return "Hover over a node to see details"

    app.run(debug=True)

network_ui()