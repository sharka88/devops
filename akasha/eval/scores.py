# coding:utf-8
from rouge import Rouge
import rouge_chinese
from bert_score import score
import jieba
import warnings
import akasha.prompts as prompts
import re
warnings.filterwarnings("ignore")
jieba.setLogLevel(jieba.logging.INFO)  ## ignore logging jieba model information

def get_bert_score(candidate_str:str, reference_str:str,langugage:str="ch", round_digit:int=3):
    """bert score using pre-trained contextual embeddings from BERT to calculate the cosine similarity between two sentences.
    So different words with similar meaning will have higher score.

    Args:
        **candidate_str (str)**: the respones generated by llm you want to test the performance.\n
        **reference_str (str)**: the default answer string.\n
        **langugage (str, optional)**: texts language. Defaults to "ch".\n
        **round_digit (int, optional)**: round the score into which digit. Defaults to 3.\n

    Returns:
        float: bert score
    """
    try:
        if langugage == "zh" or "ch":
            P, R, F1 = score([candidate_str], [reference_str], lang="zh", verbose=False)
        else :
            P, R, F1 = score([candidate_str], [reference_str], lang="en", verbose=False)
    except:
        F1 = 0.0
    # round float into 3 digits behind 0
    F1 = round(float(F1),round_digit)
    
    return F1


def get_rouge_score(candidate_str:str, reference_str:str, language:str="ch", round_digit:int=3):
    """ use jieba to separate words from chinese sentence, and then use rouge_l to calculate the rouge score
    the difference between bleu and rouge is that bleu is focus on precision, but rouge is focus on the recall.

    Args:
        **candidate_str (str)**: the respones generated by llm you want to test the performance.\n
        **reference_str (str)**: the default answer string.\n
        **langugage (str, optional)**: texts language. Defaults to "ch".\n
        **round_digit (int, optional)**: round the score into which digit. Defaults to 3.\n

    Returns:
        float: rouge score
    """
    try:
        if language == "zh" or "ch":
            rouge = rouge_chinese.Rouge(metrics=[ 'rouge-l'])
            cand = ' '.join(jieba.cut(candidate_str))
            ref = ' '.join(jieba.cut(reference_str))        
        else :    
            rouge = Rouge(metrics=[ 'rouge-l'])
            cand = candidate_str
            ref = reference_str
            
        F1 = rouge.get_scores(cand, ref)[0]['rouge-l']['f']
    except:
        F1 = 0.0
    F1 = round(F1, round_digit)
    
    return F1




def get_llm_score(candidate_str:str, reference_str:str, model, round_digit:int=3):

    prompt = prompts.format_llm_score(candidate_str, reference_str)
    try:
        response = model.predict(prompt)
            
    except:
        response = model._call(prompt)
        
    print(response)
    # find the first float number in the response string and turn to float
    try:
        score = round(float(re.findall(r"\d+\.?\d*",response)[0]),round_digit)
    except:
        score = 0.0
    return score





def get_toxic_score(texts:str, round_digit:int=3):
    
    from transformers import pipeline
    pipe = pipeline("text-classification", model="martin-ha/toxic-comment-model")
    res = pipe.predict(texts)[0]
    
    if res['label'] == 'toxic':
        score = round(float(res['score']),round_digit)
    else:
        score = round(1-float(res['score']),round_digit)
        
    return score