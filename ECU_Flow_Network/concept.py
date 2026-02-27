import dash
from dash import html, Output, Input
import dash_cytoscape as cyto

app = dash.Dash(__name__)

elements = [
    {'data': {'id': 'a', 'label': 'Node A'}},
    {'data': {'id': 'b', 'label': 'Node B'}},
    {'data': {'source': 'a', 'target': 'b', 'label': 'Edge A-B'}, 'classes': 'warning-edge'}
]

app.layout = html.Div([
    cyto.Cytoscape(
        id='cytoscape-network',
        elements=elements,
        style={'width': '600px', 'height': '400px'},
        stylesheet=[
            {'selector': 'node', 'style': {'content': 'data(label)'}},
            {'selector': '.warning-edge', 'style': {'line-color': 'yellow', 'width': 4}},
            {'selector': 'edge', 'style': {'line-color': '#ccc', 'width': 2}}
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

if __name__ == '__main__':
    app.run(debug=True)
