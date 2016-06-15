from SPARQLWrapper import SPARQLWrapper
import requests
import json

import networkx as nx

sparql = SPARQLWrapper("http://dbpedia.org/sparql", returnFormat="json")
DBPEDIA_RESOURCE_BASE = """http://dbpedia.org/resource/"""


def preprocess_text(term):
    # all lower w/ first char upper
    term = str(term[0].upper()) + str(term[1:].lower())
    # replace spaces with _
    term = term.replace(' ', '_')
    return term

def resource_exists(sparql, resource):
    exists_query = """DESCRIBE <{resource}>"""
    sparql.setQuery(exists_query.format(resource = resource))
    res = sparql.query().convert()
    exists = True if res.get('results').get('bindings') else False
    return exists

def resource_redirect(sparql, resource):
    redirect_uri = False
    redirect_qry = """PREFIX dbo: <http://dbpedia.org/ontology/>   
        SELECT ?redirect WHERE {{ 
        <{resource}> dbo:wikiPageRedirects ?redirect}}"""
    sparql.setQuery(redirect_qry.format(resource = resource))
    res = sparql.query().convert()
    if res.get('results').get('bindings'):
        redirect_uri = res.get('results').get('bindings')[0].get('redirect').get('value')
    return redirect_uri

def disambiguate_term(sparql, resource):
    candidate_uri_subjects = check_for_disambiguations(sparql, resource)
    if not candidate_uri_subjects:
        return resource
    
    ####################################
    # disambiguate terms via... (hardcoded keywords? \
    # first option? clf? cosine_sim with company description?)
    ####################################
    best_resource = candidate_uri_subjects[0].get('uri')
    return best_resource

def check_for_disambiguations(sparql, resource):
    candidate_uris = get_candidate_uris(sparql, resource)
    candidate_uri_subjects = []
    if not candidate_uris:
        return []
    
    for uri in candidate_uris:
        candidate_uri_subjects.append(dict(uri = uri, subjects = get_term_subjects(sparql, uri)))

    return candidate_uri_subjects

def get_candidate_uris(sparql, resource):
    disambig_query = """
        PREFIX dbo: <http://dbpedia.org/ontology/>    
        SELECT ?disambiguation WHERE 
        {{ <{resource}> dbo:wikiPageDisambiguates ?disambiguation }}
    """
    sparql.setQuery(disambig_query.format(resource = resource))
    res = sparql.query().convert()
    candidate_terms = [r.get('disambiguation').get('value') for r in res.get('results').get('bindings')]
    return candidate_terms

def get_term_subjects(sparql, term_uri):
    subject_query = """
        SELECT ?subject
        WHERE {{ <{term_uri}> dct:subject ?subject }}
    """
    sparql.setQuery(subject_query.format(term_uri = term_uri))
    res = sparql.query().convert()
    
    subjects = []
    try:
        subjects = [r.get('subject').get('value').split(':')[-1].replace('Category:', '').replace('_', ' ') for r in res.get('results').get('bindings')]
    except: pass
    subjects_string = stringify_alist(subjects)
    return subjects_string

def stringify_alist(alist, sep = ' '):
    return sep.join(alist)

def get_subjectsOf(sparql, resource):
    qry_subjects_of_resource = """PREFIX dct: <http://purl.org/dc/terms/>
    SELECT ?subjects WHERE {{
    <{uri}> dct:subject ?subjects .
    }}"""

    sparql.setQuery(qry_subjects_of_resource.format(uri = resource))
    res = sparql.query().convert()

    subjects = []
    if res.get('results').get('bindings'):
        subjects = [rs.get('subjects').get('value') for rs in res.get('results').get('bindings')]

    return subjects


def get_broaderAndOf(sparql, resource):
    qry_broader_and_broader_of = """SELECT ?parent_subjects ?child_subjects WHERE {{
    <{uri}> skos:broader ?parent_subjects .
    ?child_subjects skos:broader <{uri}> .
    }}"""
    
    try:
        sparql.setQuery(qry_broader_and_broader_of.format(uri = resource))
        res = sparql.query().convert()

    child_subjects = []
    parent_subjects = []
    for r in res.get('results').get('bindings'):
        child_subjects.append(r.get('child_subjects').get('value'))
        parent_subjects.append(r.get('parent_subjects').get('value'))
    return list(set(child_subjects)), list(set(parent_subjects))


def label_from_resource(uri):
    label = uri.replace(DBPEDIA_RESOURCE_BASE, '').replace('Category:', '').replace('_', ' ')
    return label


def get_term_graph(term):
    #init graph
    graph = nx.Graph()
    
    cleaned_term = preprocess_text(term)
    resource = """{resource_base}{term}""".format(term = cleaned_term, resource_base = DBPEDIA_RESOURCE_BASE)
    exists = term_exists(sparql, resource)
    if not exists:
        print 'Term resource not found.'
        return g # return empty graph
    
    resource = term_redirect(sparql, resource)
    resource = disambiguate_term(sparql, resource)
    
    subjects = get_subjectsOf(sparql, resource)
    if subjects:
        graph = build_graph(graph, subjects)
    return graph

def term_exists(sparql, resource):
    exists = resource_exists(sparql, resource)
    return exists
    
def term_redirect(sparql, resource):
    redirect = resource_redirect(sparql, resource)
    if redirect:
        resource = redirect
    return resource

def build_graph(g, subjects):
    for subject in subjects:
        child_subjects, parent_subjects = get_broaderAndOf(sparql, subject)
        # build and add layers to graph
        new_nodes, new_edges = build_layer_of_subjects(subject, child_subjects, parent_subjects)
        g = add_layer_of_subjects(g, new_nodes, new_edges)

        for child in child_subjects:
            child_child_subjects, child_parent_subjects = get_broaderAndOf(sparql, child)
            # build and add layers to graph
            new_nodes, new_edges = build_layer_of_subjects(child, child_child_subjects, child_parent_subjects)
            g = add_layer_of_subjects(g, new_nodes, new_edges)

        for parent in parent_subjects:
            parent_child_subjects, parent_parent_subjects = get_broaderAndOf(sparql, parent)
            # build and add layers to graph
            new_nodes, new_edges = build_layer_of_subjects(parent, parent_child_subjects, parent_parent_subjects)
            g = add_layer_of_subjects(g, new_nodes, new_edges)
    return g

def build_layer_of_subjects(subject, child_subjects, parent_subjects):
    new_nodes = []
    new_nodes.append(subject)

    new_edges = []
    for child in child_subjects:
        new_nodes.append(child)
        new_edges.append((subject, child))

    for parent in parent_subjects:
        new_nodes.append(parent)
        new_edges.append((subject, parent))

    return new_nodes, new_edges

def add_layer_of_subjects(G, new_nodes, new_edges):
    G.add_nodes_from(new_nodes)
    G.add_edges_from(new_edges)
    return G


def build_full_graph(terms):
    graphs = dict()
    for t in terms:
        try:
            graphs[t] = get_term_graph(t)
        except:
            pass
    G = nx.Graph()
    for g in graphs.values():
        G = nx.compose(G, g)
    return G

def get_largest_connected_subgraph(G):
    for sub in nx.connected_component_subgraphs(G):
        G = sub
        return G


def get_top_n_topics(G, top_n = 10, central_function = nx.centrality.degree_centrality):
    centr = central_function(G)
    keys = np.array(centr.keys())
    scores = np.array(centr.values())
    sort_order = np.argsort(scores)
    return keys[sort_order][::-1][:top_n]



# terms = ['facebook', 'twitter' snapchat', 'foursquare', 'myspace']

