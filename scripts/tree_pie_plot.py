#This should be run from within '2021_Delta' folder
# Note there is a  step where you need to decide
# where the 'cluster' starts! Suggest opening 'tree.nwk'
# in Figtree and checking the mutation is correct

# don't forget to set whether you want Alpha or Delta in Main!

fmt = 'pdf'
import os, sys
from Bio import Phylo
from augur.utils import read_metadata, read_node_data  #for older versions of augur - for newer need the below
#from augur.utils import read_node_data
#from augur.io import read_metadata
from augur.export_v2 import parse_node_data_and_metadata
import treetime
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import math
import json
import datetime
from shutil import copyfile
from collections import defaultdict
import copy
import pandas as pd
from colors_and_countries import *

def read_tree(treefile, metadata, alignfile=None):
    # Read in the tree, and add node data
    # make tree 'divergence' tree (collapse tiny polytomies)
    tt = treetime.TreeAnc(tree = treefile, aln =alignfile)
    tt.optimize_tree()
    T=tt.tree

    # read in extra node data and put it on the tree
    # node_data, node_attrs, node_data_names, metadata_names = parse_node_data_and_metadata(T, [nt_muts], metadata)
    meta = pd.read_csv(metadata, sep='\t', index_col=0)

    for node in T.find_clades(order='postorder'):
        node.mut_length = node.mutation_length
        if node.name in meta.index:
            node.country = meta.loc[node.name, "country"]
            node.division =meta.loc[node.name, "division"]
            node.date = meta.loc[node.name, "date"]
        else:
            node.country = ''
            node.division = ''
            node.date = ''

    #set parents to avoid excess tree-traversal
    for node in T.find_clades(order='preorder'):
        for child in node:
            child.parent = node

    return T

# Function to draw pie charts
def draw_pie(ax, ratios=[0.4,0.3,0.3], colors=["red", "blue"], X=0, Y=0, size = 1000, zorder=10):
    N = len(ratios)
    xy = []
    start = 0.
    for ratio in ratios:
        x = [0] + np.cos(np.linspace(2*math.pi*start,2*math.pi*(start+ratio), 30)).tolist()
        y = [0] + np.sin(np.linspace(2*math.pi*start,2*math.pi*(start+ratio), 30)).tolist()
        xy1 = list(zip(x,y))
        xy.append(xy1)
        start += ratio
    for i, xyi in enumerate(xy):
        ax.scatter([X],[Y] , marker=xyi, s=size, facecolor=colors[i], zorder=zorder)

# Use this function to list all nodes containing that country
# Or if you give 2 countries, nodes with both
def list_countries(wanted_country, node_countries, second_country=None):
    i=0
    for no in node_countries.keys():
        if wanted_country in node_countries[no].keys():
            if second_country:
                if second_country in node_countries[no].keys():
                    print(no,": ",node_countries[no])
                    i+=1
            else:
                print(no,": ",node_countries[no])
                i+=1
    print("total: ", i)


def list_parent_countries(wanted_country, second_country, node_countries):
    i=0
    for no in node_countries.keys():
        if wanted_country in node_countries[no].keys() and second_country not in node_countries[no].keys():
            par = parent[no]
            if second_country in node_countries[par].keys():
                print(no,": ",node_countries[no])
                i+=1
    print("total: ",i)


#use this to count countries with direct shared diversity (on same node)
def most_shared_countries(wanted_country, node_countries):
    other_country_count = defaultdict(int)
    for no in node_countries.keys():
        if wanted_country in node_countries[no].keys():
            for co in node_countries[no].keys():
                if co != wanted_country:
                    other_country_count[co]+=1
    print({k: v for k, v in sorted(other_country_count.items(), key=lambda item: item[1])})


# Create a dictionary to find nodes by name
def lookup_by_names(tree):
    names = {}
    for clade in tree.find_clades():
        if clade.name:
            if clade.name in names:
                raise ValueError("Duplicate key: %s" % clade.name)
            names[clade.name] = clade
    return names

def find_root(T, build):
    potential_roots = []
    if build == "Delta":
        root_mut = ('T',26766,'C') #note coordinates here are zero-based (off by one from Nextstrain)
    else: #alpha
        root_mut = ('C',5985,'T')
    for n in T.find_clades():
        # if ('G',24409,'A') in n.mutations: #this works for Swiss, but will change with build...
        if root_mut in n.mutations: 
            potential_roots.append(n)
    potential_roots.sort(key=lambda x:x.count_terminals())
    return potential_roots[-1]

def count_unique_sequences(tree):
    unique_seqs = 0
    for node in tree.get_nonterminals(order='postorder'):
        # if node has at least one terminal child
        has_ident_seq = False
        # cycle through children
        for leaf in node.clades:
            if leaf.is_terminal():
                mutations = list(filter(lambda x: x[2] != 'N', leaf.mutations))
                if len(mutations) > 0:
                    unique_seqs+=1
                elif len(mutations) == 0:
                    has_ident_seq = True
        if has_ident_seq:
            unique_seqs+=1

    return unique_seqs


def resample_country(node_countries, country):
    total_sequences = np.sum([x.get(country, 0) for x in node_countries.values()])

    fractions = np.linspace(0.01,1.0, 30)
    expected_intros = []
    for frac in fractions:
        expected_intros.append(np.sum([1-np.exp(-frac*x.get(country, 0)) for x in node_countries.values()]))

    return {"n_seqs":fractions*total_sequences, "expected_intros":expected_intros, "total_sequences":total_sequences}


def make_collapsed_tree(tree, selected_countries):
    # get number of unique sequences
    unique_seqs = count_unique_sequences(tree)
    #How many internals do we start with?
    print(f"number of internals pre collapsing: {len(tree.get_nonterminals())}")

    # for each internal node - if only has leaf children from 1 country
    # then collapse this node - its children go to its parent, it disappears
    for node in tree.get_nonterminals(order='postorder'):
        if node.is_preterminal():
            node.countries = []
            for leaf in node.get_terminals():
                node.countries.append(leaf.cluster_country)

            if len(set(node.countries)) == 1:
                #print("collapsing {} with {}".format(node.name, set(node.countries)))
                tree.collapse(target=node)

    #reassign parents since we deleted a bunch:
    for node in tree.find_clades(order='preorder'):
        for child in node:
            child.parent = node

    #how many internals are left?
    print(f"number of internals after collapsing: {len(tree.get_nonterminals())}")

    # A lot of nodes will have gained children from collapsed nodes
    # so recount the countries!
    for node in tree.get_nonterminals(order='postorder'):
        node.total_countries = []
        for leaf in node:
            if leaf.is_terminal():
                node.total_countries.append(leaf.cluster_country)

    # Gather up the country counts for each node:
    country_count_by_node = {}
    for node in tree.get_nonterminals(order='postorder'):
        country_count_by_node[node.name] = Counter(node.total_countries)

    return tree, country_count_by_node

def generate_putative_introduction_clusters(cluster, node_counts, fname):
    countries_clusters = {}
    for coun in node_counts.index:
        countries_clusters[coun] = defaultdict()
    #get lists of sequences per node per 'slice'
    for node in cluster.find_clades(order='postorder'):
        for child in node:
            if child.is_terminal():
                #if node.country not in countries_clusters:
                #    countries_clusters[child.country] = {}
                if node.name not in countries_clusters[child.cluster_country]:
                    countries_clusters[child.cluster_country][node.name] = {}
                    countries_clusters[child.cluster_country][node.name]["sequences"] = []
                countries_clusters[child.cluster_country][node.name]["sequences"].append(child.name)
                if hasattr(node.parent, "total_countries") and child.cluster_country in node.parent.total_countries:
                    countries_clusters[child.cluster_country][node.name]["parent"] = f"is a child of {node.parent.name}, which also contains nodes from {child.cluster_country}"

    with open(fname, 'w') as fh:
        json.dump(countries_clusters, fh)

def get_country_colors(selected_countries):
    country_colors = {}
    if len(selected_countries):
        for coun in country_styles_all:
            if coun in selected_countries:
                country_colors[coun] = country_styles_all[coun]
            else:
                country_colors[coun] = {'c': "#BBBBBB" }
    else:
        country_colors = country_styles_all

    return country_colors

def make_pie_tree(cluster, node_counts, fname, selected_countries):

    for node in cluster.get_terminals(order='postorder'):
        cluster.collapse(target=node)
    cluster.ladderize()

    # Calculate the Y plotting values for each node
    terminal_counter = 1
    for n in cluster.find_clades(order='postorder'):
        if n.is_terminal():
            n.y = terminal_counter
            terminal_counter += 1
        else:
            kids_y = [c.y for c in n]
            n.y = 0.5*(np.max(kids_y) + np.min(kids_y))

    # Calculate the X plotting values for each node
    cluster.root.x = cluster.root.branch_length
    for n in cluster.get_nonterminals(order='preorder'):
        for ci,c in enumerate(n):
            if (c.branch_length - 1.0/29900) < 1e-6:
                c.branch_length *= 0.6 + 0.8*np.random.random()
                # if (len(c)>2):
                #     c.branch_length *= 0.75 + 0.25*(ci%3)
                # else:
                #     c.branch_length *= 0.75 + 0.5*(ci%2)
            c.x = n.x + c.branch_length


    # Give each node a character name to make the easier to discuss/identify
    # Also store country counts for each node by this name (so can associate
    # the graph and data)
    ch = 'A'
    nextKey=''
    node_names = {}
    node_countries = {}
    for node in cluster.find_clades(order="preorder"):
        node.color='grey'
        new_name = nextKey+ch
        node_names[node.name] = new_name
        node_countries[new_name] = {}
        print(new_name)
        for i in range(len(node_counts.index)):
            if node_counts[node.name][i] != 0:
                print("\t", node_counts.index[i], node_counts[node.name][i])
                node_countries[new_name][node_counts.index[i]] = node_counts[node.name][i]
        if ch == "~":
            if nextKey != '':
                nextKey = chr(ord(nextKey) + 1)
            else:
                nextKey='A'
            ch='A'
        else:
            ch = chr(ord(ch) + 1)


    # Use this to to count up the nodes with wanted_country that have second_country
    # as a parent - but *not* shared diversity on the same node (only parent) (so will not
    # include nodes identified with 'list_countries')
    parent = {}
    for node in cluster.find_clades(order="preorder"):
        if node.parent and node.parent.name in node_names:
            parent[node_names[node.name]] = node_names[node.parent.name]

    # list_parent_countries(wanted_country, second_country, node_countries)

    # Actually plot!
    fs = 16
    fig = plt.figure(figsize=(12,10))
    ax = fig.add_subplot(1,1,1)
    Phylo.draw(cluster, label_func=lambda x:'', axes=ax) #,
    #           branch_labels=lambda x: ",".join([f"{a}{p+1}{d}" for a,p,d in x.mutations]))

    country_colors = get_country_colors(selected_countries)

    #make color patches for legend
    ptchs = []
    for key in selected_countries + ["Other"]:
        patch = mpatches.Patch(color=country_colors[key]['c'] if key in country_colors else '#BBBBBB', label=key)
        if key not in country_colors:
            print(f"color needed: {key}")
        ptchs.append(patch)

    def marker_size(n):
        return 30*np.sum(n)**0.5

    for node in cluster.find_clades(order="preorder"):
        counts = node_counts[node.name].to_dict()
        sqrt_counts = np.array([x for k,x in counts.items() if x>0])**0.25
        total_counts = sum(list(counts.values()))
        nonzero = [k for k,x in counts.items() if x>0]
        draw_pie(ax=plt.gca(), ratios=[x/sqrt_counts.sum() for x in sqrt_counts],
            colors=[country_colors[c]['c'] if c in country_colors else "#CCCCCC" for c in nonzero], X=node.x, Y=node.y,
            size=marker_size(total_counts))
        # plt.text(node.x+0.00001, node.y, int(sum(list(counts.values()))))
        # plt.text(node.x-0.000015, node.y, node_names[node.name] )

    for ni,n in enumerate([1,10,100, 1000]):
        ax.scatter([0.00000], [70 + ni*5], s=marker_size(n), edgecolor='k', facecolor='w')
        ax.text(0.000010, 70.8 + ni*5, f"n={n}")

    plt.axis('off')
    plt.legend(handles=ptchs, loc=3, fontsize=fs)
    plt.tight_layout()
    plt.savefig(fname)
    return node_countries, node_names

def plot_introduction_statistics(node_countries, suffix, selected_countries):
    country_colors = get_country_colors(selected_countries)
    plt.figure(figsize=(6.5,4))
    for country in selected_countries:
        res = resample_country(node_countries, country)
        plt.plot(res['n_seqs'], res['expected_intros'], label=f"{country} (n={int(res['total_sequences']):d})", lw=2,
            ls=country_colors[country]['ls'] if country in country_colors else "-",
            c=country_colors[country]['c'] if country in country_colors else "#CCCCCC")

    plt.ylabel('within country clusters')
    plt.xlabel('number of sequences')
    plt.yscale('log')
    plt.xscale('log')
    plt.legend()
    plt.savefig(figure_path + f"resampling_introductions_{suffix}{runNum}.{fmt}")

    plt.figure(figsize=(6.5,4))
    for country in selected_countries:
        counts = sorted([node_countries[n].get(country, 0) for n in node_countries if node_countries[n].get(country, 0)], reverse=True)

        plt.plot(np.arange(1, len(counts)+1), counts, label=f"{country} (s={int(sum(counts)):d}, c={len(counts)})", lw=2,
            ls=country_colors[country]['ls'] if country in country_colors else "-",
            c=country_colors[country]['c'] if country in country_colors else "#CCCCCC")

    plt.xlabel('cluster rank', fontsize=16)
    plt.ylabel('cluster size', fontsize=16)
    plt.tick_params(labelsize=13)
    plt.yscale('log')
    plt.xscale('log')
    plt.legend(ncol=2)
    plt.tight_layout()
    plt.savefig(figure_path + f"cluster_sizes_{suffix}{runNum}.{fmt}")


if __name__=="__main__":
    import argparse

    parser = parser = argparse.ArgumentParser(description='collapse phylo tree into "pies" by country',
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--run-folder', help="results of Nextstrain run")
    parser.add_argument('--variant-type', help="Specify whether Alpha or Delta build")
    parser.add_argument('--nextstrain-metadata', help="Location of Nextstrain metadata to use")
    args = parser.parse_args()

    ##
    #Input files

    #if running from ncov_2021_AlphDelt, paths are:
    # 21A.Delta-swiss_N-2021-07-31/
    # 20I.Alpha.V1-swiss_N-2021-03-31/
    #run_folder1 = "20I.Alpha.V1-swiss_1-2021-03-31" 
    #run_folder2 = "21A.Delta-swiss_1-2021-07-31" 

    run_folder = args.run_folder

    #figure out metadata folder
    #metadatafile = "../../ncov_2021_AlphDelt/data/metadata.tsv"
    metadatafile = args.nextstrain_metadata

    #figure out input files
    alignfile = f"../../ncov_2021_AlphDelt/results/{run_folder}/filtered.fasta" #use this to match number of seqs in tree!
    treefile = f"../../ncov_2021_AlphDelt/results/{run_folder}/tree.nwk"  

    #Input params
    #build = "Alpha" 
    build = args.variant_type
    #get run number #TODO how does this work with orig builds?
    if build == "Alpha":
        runNum = run_folder.replace("20I.Alpha.V1-swiss_","")
        runNum = runNum.replace("-2021-03-31","")
    else:
        runNum = run_folder.replace("21A.Delta-swiss_","")
        runNum = runNum.replace("-2021-07-31","")

    ##
    #Output files
    output_folder = f"results/{build}/"
    figure_path = f"results/{build}/figures/"
    tree_path = f"results/{build}/trees/"
    data_path = f"results/{build}/out_data/"
    if not os.path.isdir(output_folder):
        print(f"\nCouldn't find folder {output_folder} - creating it.\n")
        if not os.path.isdir("results"):
            os.mkdir("results")
    if not os.path.isdir(output_folder):
        os.mkdir(output_folder)
    if not os.path.isdir(figure_path):
        os.mkdir(figure_path)
    if not os.path.isdir(tree_path):
        os.mkdir(tree_path)
    if not os.path.isdir(data_path):
        os.mkdir(data_path)
    #else:
    #    print(f"\nOutput folder ({output_folder}) already exists. Please rename current one or delete it.\n")
    #    raise KeyboardInterrupt


    #figure this out now so we don't waste time in treetime refine then find out file is missing...
    for fi in [metadatafile, alignfile, treefile]:
        if not os.path.exists(fi):
            print("FILE NOT FOUND!")
            print(fi)
            sys.exit()


    ###############################
    ###############################

    T_backup = read_tree(treefile, metadatafile, alignfile=alignfile)

    # find the focal cluster root
    #this has to be set semi-manually by mutation
    start = find_root(T_backup, build) #send build so know what mutation to use
    print("have found cluster root")
    ######## RERUN FROM HERE

    #back up the original tree so we don't hve to optimize again if we mess up...
    T = copy.deepcopy(T_backup)
    names = lookup_by_names(T)

    #write out copy
    #Phylo.write(T_backup, f"treeFiles/{build}/treePreSubtree.nwk", "newick")
    #Phylo.write(T_backup, f"treeFiles/{build}/treePreSubtree.xml", "phyloxml")
    Phylo.write(T_backup, f"{tree_path}treePreSubtree{runNum}.nwk", "newick")
    Phylo.write(T_backup, f"{tree_path}treePreSubtree{runNum}.xml", "phyloxml")


    #Make a subtree of the cluster so we can just work with that
    cluster = T.from_clade(names[start.name])
    #check counts match what expect:  T_backup.count_terminals() & cluster.count_terminals()
    select_run = True
    uk_run = False
    if select_run:
        #selected_countries = ["Spain", "Switzerland", "United Kingdom", "Ireland", "Denmark", "Norway", "Iceland", "Netherlands"]
        selected_countries = ["Spain", "Switzerland", "United Kingdom", "USA", "India", "Germany", "France", "Italy", "Russia", "Portugal", "Denmark"]
    else:
        selected_countries = list({n.country for n in cluster.get_terminals()})

    if uk_run:
        selected_countries.extend(['Scotland', 'England', 'Wales', 'Northern Ireland'])

    for leaf in cluster.get_terminals():
        if uk_run and leaf.country == "United Kingdom":
            leaf.cluster_country = leaf.division
        elif leaf.country in selected_countries:
            leaf.cluster_country = leaf.country
        else:
            leaf.cluster_country = "Other"

    cT, country_count_by_node = make_collapsed_tree(cluster, selected_countries)

    # make dataframe out of the counts
    node_counts = pd.DataFrame(data=country_count_by_node)
    node_counts = node_counts.fillna(0)
    node_counts = node_counts.sort_index()

    #Phylo.write(cT, f"treeFiles/{build}/treeSubtree.xml", "phyloxml")
    #Phylo.write(cT, f"treeFiles/{build}/treeSubtree.nwk", "newick")
    Phylo.write(cT, f"{tree_path}treeSubtree{runNum}.xml", "phyloxml")
    Phylo.write(cT, f"{tree_path}treeSubtree{runNum}.nwk", "newick")

    #save leaf data out to be accessed elsewhere
    final_node_data = defaultdict(dict)
    for leaf in cluster.get_terminals():
        final_node_data[leaf.name] = {"country": leaf.country, "division": leaf.division,
                                      "date": leaf.date}
    (pd.DataFrame.from_dict(data=final_node_data, orient='index')
        .to_csv(f'{tree_path}tree_data{runNum}.csv', header=True))


    #generate_putative_introduction_clusters(cT, node_counts, f"through_{'Nov' if untilNov else 'Sep'}_data/pie_slices.json")
    generate_putative_introduction_clusters(cT, node_counts, f"{data_path}pie_slices{runNum}.json")

    #Copy our cluster, and then delete/collapse all the tips! (for plotting)
    cluster2 = copy.deepcopy(cT)

    #node_countries = make_pie_tree(cluster2, node_counts, f"figures/pie_tree_{'Nov' if untilNov else 'Sep'}.{fmt}")
    node_countries, node_names = make_pie_tree(cluster2, node_counts, f"{figure_path}pie_tree{runNum}.{fmt}", selected_countries)

    plot_introduction_statistics(node_countries, build, selected_countries)
