from fastapi import FastAPI, APIRouter
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
import akasha
import akasha.helper
import akasha.db
import os
import json
import api_utils as apu
import subprocess

DATASET_CONFIG_PATH = apu.get_dataset_config_path()
DOCS_PATH = apu.get_docs_path()
CONFIG_PATH = apu.get_config_path()
MODEL_PATH = apu.get_model_path()
MODEL_NAME_PATH = apu.get_model_name_path()


class UserID(BaseModel):
    owner: str


class DatasetID(UserID):
    dataset_name: str


class DatasetShare(DatasetID):
    shared_users: Optional[List[str]] = []


class DatasetShareDelete(DatasetID):
    delete_users: Optional[List[str]] = []


class DatasetInfo(DatasetID):
    dataset_description: Optional[str] = ""


class EditDatasetInfo(DatasetInfo):
    new_dataset_name: str
    new_dataset_description: Optional[str] = ""
    upload_files: Optional[List[str]] = []
    delete_files: Optional[List[str]] = []


router = APIRouter()


@router.get("/get_base_config_path")
def get_base_config_path():
    return {'status': 'success', 'response': CONFIG_PATH}


@router.get("/get_dataset_config_path")
def get_dataset_config_path():
    return {'status': 'success', 'response': DATASET_CONFIG_PATH}


@router.get("/get_docs_path")
def get_docs_path():
    return {'status': 'success', 'response': DOCS_PATH}


@router.get("/get_model_path")
def get_model_path():

    ### get base models
    if not Path(MODEL_NAME_PATH).exists():
        ## create a txt file to store default model names
        base = [
            "openai:gpt-3.5-turbo", "openai:gpt-3.5-turbo-16k", "openai:gpt-4",
            "openai:gpt-4-32k"
        ]
        with open(MODEL_NAME_PATH, 'w') as f:
            for model in base:
                f.write(model + '\n')
    else:
        with open(MODEL_NAME_PATH, 'r') as f:
            base = f.readlines()
        base = [model_name.strip().strip('\n') for model_name in base]

    vis = set(base)

    try:
        modes_dir = MODEL_PATH
        for dir_path in Path(modes_dir).iterdir():
            if dir_path.is_dir():
                if ("gptq" in dir_path.name) or ("GPTQ" in dir_path.name):
                    mdl_whole_name = "gptq:" + (Path(modes_dir) /
                                                dir_path.name).__str__()
                    if mdl_whole_name not in vis:
                        base.append(mdl_whole_name)
                        vis.add(mdl_whole_name)
                else:
                    mdl_whole_name = "hf:" + (Path(modes_dir) /
                                              dir_path.name).__str__()
                    if mdl_whole_name not in vis:
                        base.append(mdl_whole_name)
                        vis.add(mdl_whole_name)

            elif dir_path.suffix == ".gguf":
                mdl_whole_name = "llama-gpu:" + (Path(modes_dir) /
                                                 dir_path.name).__str__()
                if mdl_whole_name not in vis:
                    base.append(mdl_whole_name)
                    vis.add(mdl_whole_name)
    except:
        print("can not find model folder!\n\n")
        # create model folder
        subprocess.run(["mkdir", "-p", modes_dir])
    return {'status': 'success', 'response': base}


@router.post("/dataset/create")
def create_dataset(user_input: DatasetInfo):
    """create dataset config file and save to DATASET_CONFIG_PATH, the .json file name is the md5 hash of
    dataset_name + '-' + owner(uid), and each file in DOC_PATH/owner/dataset_name will be added to the config file, with it's md5 hash.
    dataset config in clude:
        "uid": str, hash of dataset_name + '-' + owner
        "name": str, dataset_name
        "description": str, dataset_description
        "owner": str,  owner
        "files": list of dictionary include document filename and MD5 hash of file
        "last_update": the last update time of document in dataset
    Args:
        user_input (DatasetInfo): data input class used in create_dataset
        dataset_description: Optional[str] = ""
        dataset_name : str
        owner : str
    Returns:
        dict: status, response
    """
    dataset_name = user_input.dataset_name
    dataset_description = user_input.dataset_description
    owner = user_input.owner

    uid = apu.generate_hash(owner, dataset_name)
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    save_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    own_path = Path(DOCS_PATH) / owner
    if not apu.check_dir(own_path):
        return {
            'status': 'fail',
            'response': 'create document path failed.\n\n'
        }
    doc_path = (own_path / dataset_name)

    ## list all files path in doc_path and get their md5 hash
    file_paths = list(doc_path.glob('*'))
    md5_list = []
    for file_path in file_paths:
        file_doc = akasha.db._load_file(file_path.__str__(),
                                        file_path.name.split('.')[-1])
        if file_doc == "" or len(file_doc) == 0:
            md5_hash = ""
        else:
            md5_hash = akasha.helper.get_text_md5(''.join(
                [fd.page_content for fd in file_doc]))

        md5_list.append(md5_hash)

    ## create dict and save to json file
    data = {
        "uid":
        uid,
        "name":
        dataset_name,
        "description":
        dataset_description,
        "owner":
        owner,
        "files": [{
            "filename": file_paths[i].name,
            "MD5": md5_list[i]
        } for i in range(len(file_paths))],
        "last_update":
        apu.get_lastupdate_of_dataset(dataset_name, owner)
    }

    ## write json file
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    return {
        'status': 'success',
        'response': f'create dataset {dataset_name} successfully.\n\n'
    }


@router.post("/dataset/update")
def update_dataset(user_input: EditDatasetInfo):
    """
    1. update dataset config file and save to DATASET_CONFIG_PATH, delete chromadb generated by delete_files,
    2. remove delete_files config from data['files'],  
    3. add upload_files config to data['files'], update dataset name, description, last_update
    4. remove delete file's chromadb directory
    5. update chromadb directory name if dataset name changed. update expert which has this dataset,
    6. remove files that have been deleted and update dataset name if dataset name changed.
    
    Args:
        user_input (DatasetInfo): data input class used in update_dataset
        dataset_description: Optional[str] = ""
        dataset_name : str
        owner : str
        new_dataset_name: str
        new_dataset_description: Optional[str] = ""
        upload_files: Optional[List[str]] = []
        delete_files: Optional[List[str]] = []
    Returns:
        dict: status, response
    """
    dataset_name = user_input.dataset_name
    owner = user_input.owner
    new_dataset_name = user_input.new_dataset_name
    dataset_description = user_input.new_dataset_description
    upload_files = user_input.upload_files
    delete_files = user_input.delete_files
    uid = apu.generate_hash(owner, dataset_name)
    old_dataset_name = dataset_name
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    ## delete Path(DATASET_CONFIG_PATH) / (uid+'.json') file
    os.remove(data_path)

    if dataset_name != new_dataset_name:
        ### edit config name
        uid = apu.generate_hash(owner, new_dataset_name)
        data['name'] = new_dataset_name
        data['uid'] = uid
        dataset_name = new_dataset_name

    save_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    own_path = Path(DOCS_PATH) / owner
    if not apu.check_dir(own_path):
        return {
            'status': 'fail',
            'response': 'create document path failed.\n\n'
        }
    doc_path = own_path / dataset_name
    new_files = []

    old_md5_list = [
    ]  # get all md5 hash of files in order to change chromadb directory name
    ### delete chromadb generated by delete_files
    for dic in data['files']:
        if dic['MD5'] != "":
            old_md5_list.append(dic['MD5'])
        if dic['filename'] in delete_files:
            md5 = dic['MD5']
            if md5 != "":
                akasha.helper.del_path('./chromadb/',
                                       old_dataset_name + '_' + md5)

    ### remove delete_files config from data['files']

    for dic in data['files']:
        if dic['filename'] not in delete_files:
            new_files.append(dic)

    exi_files = set([dic['filename'] for dic in data['files']])
    ### add upload_files config to data['files']
    for file in upload_files:
        if file in exi_files:
            continue
        file_doc = akasha.db._load_file((doc_path / file).__str__(),
                                        file.split('.')[-1])
        if file_doc == "" or len(file_doc) == 0:
            md5_hash = ""
        else:
            md5_hash = akasha.helper.get_text_md5(''.join(
                [fd.page_content for fd in file_doc]))
        new_files.append({"filename": file, "MD5": md5_hash})

    ## update dataset name in chromadb
    if old_dataset_name != dataset_name:
        apu.update_dataset_name_from_chromadb(old_dataset_name, dataset_name,
                                              old_md5_list)

    ## update dict and save to json file
    data['files'] = new_files
    data['description'] = dataset_description
    data['last_update'] = apu.get_lastupdate_of_dataset(dataset_name, owner)

    ## write json file
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    ### update expert which has this dataset, remove files that have been deleted, also update dataset name if dataset name changed.
    apu.check_and_delete_files_from_expert(dataset_name, owner, delete_files,
                                           old_dataset_name)
    return {
        'status': 'success',
        'response': f'update dataset {dataset_name} successfully.\n\n'
    }


@router.post("/dataset/delete")
def delete_dataset(user_input: DatasetID):
    """delete dataset config file and remove chromadb generated by this dataset's files

    Args:
        user_input (DatasetID): used in delete_dataset and some get dataset info api function
        dataset_name : str
        owner : str
    Returns:
        dict: status, response
    """
    owner = user_input.owner
    dataset_name = user_input.dataset_name

    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)
    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {
            'status': 'fail',
            'response': 'dataset config file not found.\n\n'
        }

    ## delete chromadbs generated by this dataset's files
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for file in data['files']:
        md5 = file['MD5']
        if md5 != "":
            akasha.helper.del_path('./chromadb/', dataset_name + '_' + md5)

    ## delete Path(DATASET_CONFIG_PATH) / (uid+'.json') file
    os.remove(data_path)

    ## delete this dataset in every expert's dataset list
    apu.check_and_delete_dataset(dataset_name, owner)
    return {
        'status': 'success',
        'response': f'delete dataset {dataset_name} successfully.\n\n'
    }


@router.post("/dataset/share")
def share_dataset(user_input: DatasetShare):
    """add 'shared_users' into dataset config file

    Args:
        user_input (DatasetShare): _description_
        owner : str
        dataset_name : str
        shared_users : list of str

    Returns:
        dict: status, response
    """
    owner = user_input.owner
    dataset_name = user_input.dataset_name
    shared_users = user_input.shared_users

    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)
    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {
            'status': 'fail',
            'response': 'dataset config file not found.\n\n'
        }

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if 'shared_users' not in data.keys():
        data['shared_users'] = []

    ### add shared users into data['shared_users']
    # vis = set(data['shared_users'])
    # for user in shared_users:
    #     vis.add(user)

    data['shared_users'] = list(set(shared_users))

    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    return {
        'status': 'success',
        'response': f'share dataset {dataset_name} successfully.\n\n'
    }


@router.post("/dataset/delete_share")
def delete_share_dataset(user_input: DatasetShareDelete):
    """delete users that in delete_users from shared users in dataset config file

    Args:
        user_input (DatasetShareDelete):
        owner : str
        dataset_name : str
        delete_users : list of str 

    Returns:
        dict: status, resonse
    """
    owner = user_input.owner
    dataset_name = user_input.dataset_name
    delete_users = user_input.delete_users

    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)
    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {
            'status': 'fail',
            'response': 'dataset config file not found.\n\n'
        }

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if 'shared_users' not in data.keys() or len(data['shared_users']) == 0:
        data['shared_users'] = []
        return {
            'status': 'fail',
            'response': 'dataset not shared to any user.\n\n'
        }

    ### add shared users into data['shared_users']
    vis = set(data['shared_users'])
    for user in delete_users:
        if user in vis:
            vis.remove(user)

    data['shared_users'] = list(vis)

    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    return {
        'status': 'success',
        'response': f'edit shared users {dataset_name} successfully.\n\n'
    }


@router.get("/dataset/get_dcp")
def get_description_from_dataset(user_input: DatasetID):
    """input the current user id and dataset name, return the description of dataset(str)

    Args:
        user_input (DatasetID): _description_
        owner : str
        dataset_name : str
    Returns:
        dict: status, response(description)
    """
    owner = user_input.owner
    dataset_name = user_input.dataset_name
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)
    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {
            'status': 'fail',
            'response': 'dataset config file not found.\n\n'
        }

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if "description" not in data.keys():
        return {
            'status': 'fail',
            'response': 'dataset description not found.\n\n'
        }
    return {'status': 'success', 'response': data['description']}


@router.get("/dataset/get_md5")
def get_MD5_list_from_dataset(user_input: DatasetID):
    """input the current user id and dataset name, return the dataset's all file's md5 hash(list)

    Args:
        user_input (DatasetID): _description_
        owner : str
        dataset_name : str
    Returns:
        dict: status, response(md5 hash list)
    """

    owner = user_input.owner
    dataset_name = user_input.dataset_name
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)
    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {
            'status': 'fail',
            'response': 'dataset config file not found.\n\n'
        }

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    response = {}
    for file in data['files']:
        if file['MD5'] != "":
            response[file['filename']] = file['MD5']
    return {'status': 'success', 'response': response}


@router.get("/dataset/get_filename")
def get_filename_list_from_dataset(user_input: DatasetID):
    """input the current user id and dataset name, return the dataset's all file's file name(list)

    
    Args:
        user_input (DatasetID): _description_
        owner : str
        dataset_name : str
    Returns:
        dict: status, response(file name list)
    """

    owner = user_input.owner
    dataset_name = user_input.dataset_name
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)
    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {
            'status': 'fail',
            'response': 'dataset config file not found.\n\n'
        }

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    response = []
    for file in data['files']:
        if file['filename'] != "":
            response.append(file['filename'])
    return {'status': 'success', 'response': response}


@router.get("/dataset/show")
def get_info_of_dataset(user_input: DatasetID):
    """input the current user id and dataset name, return the dataset info(dict)

    Args:
        user_input (DatasetID): _description_
        owner : str
        dataset_name : str
    Returns:
        dict: status, response(dataset config dictionary)
    """
    owner = user_input.owner
    dataset_name = user_input.dataset_name
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    uid = apu.generate_hash(owner, dataset_name)

    data_path = Path(DATASET_CONFIG_PATH) / (uid + '.json')
    if not data_path.exists():
        return {'status': 'fail', 'response': 'dataset not found.\n\n'}

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return {'status': 'success', 'response': data}


@router.get("/dataset/get_owner")
def get_owner_dataset_list(user_input: UserID):
    """input current user id, return all dataset name and its owner name that owner is current user(list of dict)

    Args:
        user_input (UserID): _description_
        owner : str
    Returns:
        dict: status, response(list of dict)
    """
    owner = user_input.owner
    dataset_names = []
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    ## get all dataset name
    p = Path(DATASET_CONFIG_PATH)
    for file in p.glob("*"):
        with open(file, 'r', encoding='utf-8') as file:
            dataset = json.load(file)
        if dataset['owner'] == owner:
            dataset_names.append({
                'dataset_name': dataset['name'],
                'owner': dataset['owner']
            })
    return {'status': 'success', 'response': dataset_names}


@router.get("/dataset/get")
def get_use_dataset_list(user_input: UserID):
    """input current user id, return all dataset name and its owner name that current user can use(list of dict)

    Args:
        user_input (UserID): _description_
        owner : str
    Returns:
        dict: status, response(list of dict)
    """
    owner = user_input.owner
    dataset_names = []
    if not apu.check_config(DATASET_CONFIG_PATH):
        return {'status': 'fail', 'response': 'create config path failed.\n\n'}

    ## get all dataset name
    p = Path(DATASET_CONFIG_PATH)
    for file in p.glob("*"):
        with open(file, 'r', encoding='utf-8') as file:
            dataset = json.load(file)
        if dataset['owner'] == owner:
            dataset_names.append({
                'dataset_name': dataset['name'],
                'owner': dataset['owner']
            })
        elif 'shared_users' in dataset.keys(
        ) and owner in dataset['shared_users']:
            dataset_names.append({
                'dataset_name': dataset['name'],
                'owner': dataset['owner']
            })
    return {'status': 'success', 'response': dataset_names}