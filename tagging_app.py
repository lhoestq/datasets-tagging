import copy
import datasets
import json
import os
import streamlit as st
from pathlib import Path
import yaml
from typing import Dict

from dataclasses import asdict
from glob import glob
from os.path import join as pjoin

st.set_page_config(
    page_title="HF Dataset Tagging App",
    page_icon="https://huggingface.co/front/assets/huggingface_logo.svg",
    layout="wide",
    initial_sidebar_state="auto",
)

task_set = json.load(open("task_set.json"))
license_set = json.load(open("license_set.json"))
language_set_restricted = json.load(open("language_set.json"))
language_set = json.load(open("language_set_full.json"))

multilinguality_set = {
    "monolingual": "contains a single language",
    "multilingual": "contains multiple languages",
    "translation": "contains translated or aligned text",
    "other": "other type of language distribution",
}

creator_set = {
    "language": [
        "found",
        "crowdsourced",
        "expert-generated",
        "machine-generated",
        "other",
    ],
    "annotations": [
        "found",
        "crowdsourced",
        "expert-generated",
        "machine-generated",
        "no-annotation",
        "other",
    ],
}

########################
## Helper functions
########################

@st.cache
def filter_features(feature_dict):
    if feature_dict.get("_type", None) == 'Value':
        return {
            "feature_type": feature_dict["_type"],
            "dtype": feature_dict["dtype"],
        }
    elif feature_dict.get("_type", None) == 'Sequence':
        if "dtype" in feature_dict["feature"]:
            return {
                "feature_type": feature_dict["_type"],
                "feature": filter_features(feature_dict["feature"]),
            }
        else:
            return dict(
                [("feature_type", feature_dict["_type"])] + \
                [(k, filter_features(v)) for k, v in feature_dict["feature"].items()]
            )
    elif feature_dict.get("_type", None) == 'ClassLabel':
        return {
            "feature_type": feature_dict["_type"],
            "dtype": "int32",
            "class_names": feature_dict["names"],
        }
    elif feature_dict.get("_type", None) in ['Translation', 'TranslationVariableLanguages']:
        return {
            "feature_type": feature_dict["_type"],
            "dtype": "string",
            "languages": feature_dict["languages"],
        }
    else:
        return dict([(k, filter_features(v)) for k, v in feature_dict.items()])

@st.cache
def find_languages(feature_dict):
    if type(feature_dict) in [dict, datasets.features.Features]:
        languages = [l for l in feature_dict.get('languages', [])]
        for k, v in feature_dict.items():
            languages += [l  for l in find_languages(v)]
        return languages
    else:
        return []

keep_keys = ['description', 'features', 'homepage', 'license', 'splits']

def load_existing_tags():
    has_tags = {}
    for fname in glob("saved_tags/*/*/tags.json"):
        _, did, cid, _ = fname.split(os.sep)
        has_tags[did] = has_tags.get(did, {})
        has_tags[did][cid] = fname
    return has_tags

########################
## Dataset selection
########################

st.sidebar.markdown(
    """<center>
<a href="https://github.com/huggingface/datasets">
<img src="https://raw.githubusercontent.com/huggingface/datasets/master/docs/source/imgs/datasets_logo_name.jpg" width="200"></a>
</center>""",
    unsafe_allow_html=True,
)

app_desc = """
### Dataset Tagger

This app aims to make it easier to add structured tags to the datasets present in the library.

Each configuration requires its own tasks, as these often correspond to distinct sub-tasks. However, we provide the opportunity
to pre-load the tag sets from another dataset or configuration to avoid too much redundancy.

The tag sets are saved in JSON format, but you can print a YAML version in the right-most column to copy-paste to the config README.md
"""

existing_tag_sets = load_existing_tags()
all_dataset_ids = list(existing_tag_sets.keys())

st.sidebar.markdown(app_desc)

# option to only select from datasets that still need to be annotated
only_missing = st.sidebar.checkbox("Show only un-annotated configs")


dataset_id = "local dataset"

all_info_dicts = {}
if dataset_id == "local dataset":
    path_to_info = st.sidebar.text_input("Please enter the path to the folder where the dataset_infos.json file was generated", "/path/to/dataset/")
    if path_to_info != "/path/to/dataset/":
        dataset_infos = json.load(open(pjoin(path_to_info, "dataset_infos.json")))
        confs = dataset_infos.keys()
        all_info_dicts = {}
        for conf, info in dataset_infos.items():
            conf_info_dict = dict([(k, info[k]) for k in keep_keys])
            all_info_dicts[conf] = conf_info_dict
        dataset_id = list(dataset_infos.values())[0]["builder_name"]
    else:
        dataset_id = "tmp_dir"
        all_info_dicts = {
            "default":{
                'description': "",
                'features': {},
                'homepage': "",
                'license': "",
                'splits': {},
            }
        }

if only_missing:
    config_choose_list = [cid for cid in all_info_dicts
                              if not cid in existing_tag_sets.get(dataset_id, {})]
else:
    config_choose_list = list(all_info_dicts.keys())

config_id = st.sidebar.selectbox(
    label="Choose configuration",
    options=config_choose_list,
)

config_infos = all_info_dicts[config_id]

c1, _, c2, _, c3 = st.beta_columns([8, 1, 14, 1, 10])

########################
## Dataset description
########################

data_desc = f"### Dataset: {dataset_id} | Configuration: {config_id}" + "\n"
data_desc += f"[Homepage]({config_infos['homepage']})" + " | "
data_desc += f"[Data script](https://github.com/huggingface/datasets/blob/master/datasets/{dataset_id}/{dataset_id}.py)" + " | "
data_desc += f"[View examples](https://huggingface.co/nlp/viewer/?dataset={dataset_id}&config={config_id})"
c1.markdown(data_desc)

with c1.beta_expander("Dataset description:", expanded=True):
    st.markdown(config_infos['description'])

# "pretty-fy" the features to be a little easier to read
features = filter_features(config_infos['features'])
with c1.beta_expander(f"Dataset features for config: {config_id}", expanded=True):
    st.write(features)

########################
## Dataset tagging
########################

c2.markdown(f"### Writing tags for: {dataset_id} / {config_id}")

##########
# Pre-load information to speed things up
##########
c2.markdown("#### Pre-loading an existing tag set")

pre_loaded = {
    "task_categories": [],
    "task_ids": [],
    "multilinguality": [],
    "languages": [],
    "language_creators": [],
    "annotations_creators": [],
    "source_datasets": [],
    "size_categories": [],
    "licenses": [],
}

if existing_tag_sets.get(dataset_id, {}).get(config_id, None) is not None:
    existing_tags_fname = existing_tag_sets[dataset_id][config_id]
    c2.markdown(f"#### Attention: this config already has a tagset saved in {existing_tags_fname}\n---  \n")
    if c2.checkbox("pre-load existing tag set"):
        pre_loaded = json.load(open(existing_tags_fname))

c2.markdown("> *You may choose to pre-load the tag set of another dataset or configuration:*")

with c2.beta_expander("- Choose tag set to pre-load"):
    did_choice_list = list(existing_tag_sets.keys())
    if len(existing_tag_sets) > 0:
        did = st.selectbox(
            label="Choose dataset to load tag set from",
            options=did_choice_list,
            index=did_choice_list.index(dataset_id) if dataset_id in did_choice_list else 0,
        )
        cid = st.selectbox(
            label="Choose config to load tag set from",
            options=list(existing_tag_sets[did].keys()),
            index=0,
        )
        if st.checkbox("pre-load this tag set"):
            pre_loaded = json.load(open(existing_tag_sets[did][cid]))
    else:
        st.write("There are currently no other saved tag sets.")

pre_loaded["languages"] = list(set(pre_loaded["languages"] + find_languages(features)))
if config_infos["license"] in license_set:
    pre_loaded["licenses"] = list(set(pre_loaded["licenses"] + [config_infos["license"]]))

##########
# Modify or add new tags
##########
c2.markdown("#### Editing the tag set")
c2.markdown("> *Expand the following boxes to edit the tag set. For each of the questions, choose all that apply, at least one option:*")

with c2.beta_expander("- Supported tasks"):
    task_categories = st.multiselect(
        "What categories of task does the dataset support?",
        options=list(task_set.keys()),
        default=pre_loaded["task_categories"],
        format_func=lambda tg: f"{tg} : {task_set[tg]['description']}",
    )
    task_specifics = []
    for tg in task_categories:
        task_specs = st.multiselect(
            f"What specific *{tg}* tasks does the dataset support?",
            options=task_set[tg]["options"],
            default=[ts for ts in pre_loaded["task_ids"] if ts in task_set[tg]["options"]],
        )
        if "other" in task_specs:
            other_task = st.text_input(
                "You selected 'other' task. Please enter a short hyphen-separated description for the task:",
                value='my-task-description',
            )
            st.write(f"Registering {tg}-other-{other_task} task")
            task_specs[task_specs.index("other")] = f"{tg}-other-{other_task}"
        task_specifics += task_specs

with c2.beta_expander("- Languages"):
    multilinguality = st.multiselect(
        "Does the dataset contain more than one language?",
        options=list(multilinguality_set.keys()),
        default=pre_loaded["multilinguality"],
        format_func= lambda m: f"{m} : {multilinguality_set[m]}",
    )
    if "other" in multilinguality:
        other_multilinguality = st.text_input(
            "You selected 'other' type of multilinguality. Please enter a short hyphen-separated description:",
            value='my-multilinguality',
        )
        st.write(f"Registering other-{other_multilinguality} multilinguality")
        multilinguality[multilinguality.index("other")] = f"other-{other_multilinguality}"
    languages = st.multiselect(
        "What languages are represented in the dataset?",
        options=list(language_set.keys()),
        default=pre_loaded["languages"],
        format_func= lambda m: f"{m} : {language_set[m]}",
    )

with c2.beta_expander("- Dataset creators"):
    language_creators = st.multiselect(
        "Where does the text in the dataset come from?",
        options=creator_set["language"],
        default=pre_loaded["language_creators"],
    )
    annotations_creators = st.multiselect(
        "Where do the annotations in the dataset come from?",
        options=creator_set["annotations"],
        default=pre_loaded["annotations_creators"],
    )
    licenses = st.multiselect(
        "What licenses is the dataset under?",
        options=list(license_set.keys()),
        default=pre_loaded["licenses"],
        format_func= lambda l: f"{l} : {license_set[l]}",
    )
    if "other" in licenses:
        other_license = st.text_input(
            "You selected 'other' type of license. Please enter a short hyphen-separated description:",
            value='my-license',
        )
        st.write(f"Registering other-{other_license} license")
        licenses[licenses.index("other")] = f"other-{other_license}"
    # link ro supported datasets
    pre_select_ext_a = []
    if "original" in pre_loaded["source_datasets"]:
        pre_select_ext_a += ["original"]
    if any([p.startswith("extended") for p in pre_loaded["source_datasets"]]):
        pre_select_ext_a += ["extended"]
    extended = st.multiselect(
        "Does the dataset contain original data and/or was it extended from other datasets?",
        options=["original", "extended"],
        default=pre_select_ext_a,
    )
    source_datasets = ["original"] if "original" in extended else []
    if "extended" in extended:
        pre_select_ext_b = [p.split('|')[1] for p in pre_loaded["source_datasets"] if p.startswith("extended")]
        extended_sources = st.multiselect(
            "Which other datasets does this one use data from?",
            options=all_dataset_ids,
            default=pre_select_ext_b,
        )
        if "other" in extended_sources:
            other_extended_sources = st.text_input(
                "You selected 'other' dataset. Please enter a short hyphen-separated description:",
                value='my-dataset',
            )
            st.write(f"Registering other-{other_extended_sources} dataset")
            extended_sources[extended_sources.index("other")] = f"other-{other_extended_sources}"
        source_datasets += [f"extended|{src}" for src in extended_sources]

num_examples = (
    sum([dct.get('num_examples', 0) for spl, dct in config_infos['splits'].items()])
    if config_infos.get('splits', None) is not None
    else -1
)
if num_examples < 0:
    size_cat = "unknown"
elif num_examples < 1000:
    size_cat = "n<1K"
elif num_examples < 10000:
    size_cat = "1K<n<10K"
elif num_examples < 100000:
    size_cat = "10K<n<100K"
elif num_examples < 1000000:
    size_cat = "100K<n<1M"
else:
    size_cat = "n>1M"

res = {
    "task_categories": task_categories,
    "task_ids": task_specifics,
    "multilinguality": multilinguality,
    "languages": languages,
    "language_creators": language_creators,
    "annotations_creators": annotations_creators,
    "source_datasets": source_datasets,
    "size_categories": [size_cat],
    "licenses": licenses,
}

########################
## Show results
########################
c3.markdown("### Finalized tag set:")

if c3.button("Done? Save to File!"):
    if not os.path.isdir(pjoin('saved_tags', dataset_id)):
        _ = os.mkdir(pjoin('saved_tags', dataset_id))
    if not os.path.isdir(pjoin('saved_tags', dataset_id, config_id)):
        _ = os.mkdir(pjoin('saved_tags', dataset_id, config_id))
    json.dump(res, open(pjoin('saved_tags', dataset_id, config_id, 'tags.json'), 'w'))

with c3.beta_expander("Show JSON output for the current config"):
    st.write(res)

with c3.beta_expander("Show YAML output aggregating the tags saved for all configs"):
    task_saved_configs = dict([
        (Path(fname).parent.name, json.load(open(fname)))
        for fname in glob(f"saved_tags/{dataset_id}/*/tags.json")
    ])
    aggregate_config = {}
    for conf_name, saved_tags in task_saved_configs.items():
        for tag_k, tag_ls in saved_tags.items():
            aggregate_config[tag_k] = aggregate_config.get(tag_k, {})
            aggregate_config[tag_k][conf_name] = tuple(sorted(tag_ls))
    for tag_k in aggregate_config:
        if len(set(aggregate_config[tag_k].values())) == 1:
            aggregate_config[tag_k] = list(list(set(aggregate_config[tag_k].values()))[0])
        else:
            for conf_name in aggregate_config[tag_k]:
                aggregate_config[tag_k][conf_name] = list(aggregate_config[tag_k][conf_name])
    st.text(yaml.dump(aggregate_config))

c3.markdown("---  ")

with c3.beta_expander("----> show full task set <----", expanded=True):
    st.write(task_set)
