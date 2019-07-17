import argparse
import glob
import json
import logging
import os

import numpy as np
from pomegranate import BayesianNetwork
from sklearn.ensemble import AdaBoostClassifier
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, r2_score
from sklearn.mixture import GaussianMixture
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.tree import DecisionTreeClassifier

from sdgym.synthesizers.utils import CATEGORICAL, CONTINUOUS, ORDINAL

logging.basicConfig(level=logging.INFO)


BAYESIAN_PARAMETER = {
    'grid': 30,
    'gridr': 30,
    'ring': 10,
}


def default_multi_classification(x_train, y_train, x_test, y_test, classifiers):
    """Score classifiers using f1 score and the given train and test data.

    Args:
        x_train(numpy.ndarray):
        y_train(numpy.ndarray):
        x_test(numpy.ndarray):
        y_test(numpy):
        classifiers(list):

    Returns:
        list[dict]:


    """
    performance = []
    for clf, name in classifiers:
        unique_labels = np.unique(y_train)
        if len(unique_labels) == 1:
            pred = [unique_labels[0]] * len(x_test)
        else:
            clf.fit(x_train, y_train)
            pred = clf.predict(x_test)

        acc = accuracy_score(y_test, pred)
        macro_f1 = f1_score(y_test, pred, average='macro')
        micro_f1 = f1_score(y_test, pred, average='micro')

        performance.append(
            {
                "name": name,
                "accuracy": acc,
                "macro_f1": macro_f1,
                "micro_f1": micro_f1
            }
        )

    return performance


def default_binary_classification(x_train, y_train, x_test, y_test, classifiers):
    performance = []
    for clf, name in classifiers:
        unique_labels = np.unique(y_train)
        if len(unique_labels) == 1:
            pred = [unique_labels[0]] * len(x_test)
        else:
            clf.fit(x_train, y_train)
            pred = clf.predict(x_test)

        acc = accuracy_score(y_test, pred)
        f1 = f1_score(y_test, pred, average='binary')

        performance.append(
            {
                "name": name,
                "accuracy": acc,
                "f1": f1
            }
        )

    return performance


def news_regression(x_train, y_train, x_test, y_test, regressors):
    performance = []
    y_train = np.log(np.clip(y_train, 1, 20000))
    y_test = np.log(np.clip(y_test, 1, 20000))
    for clf, name in regressors:
        clf.fit(x_train, y_train)
        pred = clf.predict(x_test)

        r2 = r2_score(y_test, pred)

        performance.append(
            {
                "name": name,
                "r2": r2,
            }
        )

    return performance


def make_features(data, meta, label_column='label', label_type='int', sample=50000):
    data = data.copy()
    np.random.shuffle(data)
    data = data[:sample]

    features = []
    labels = []

    for row in data:
        feature = []
        label = None
        for col, cinfo in zip(row, meta):
            if cinfo['name'] == 'label':
                if label_type == 'int':
                    label = int(col)
                elif label_type == 'float':
                    label = float(col)
                else:
                    assert 0, 'unkown label type'
                continue

            if cinfo['type'] == CONTINUOUS:
                if cinfo['min'] >= 0 and cinfo['max'] >= 1e3:
                    feature.append(np.log(max(col, 1e-2)))
                else:
                    feature.append((col - cinfo['min']) / (cinfo['max'] - cinfo['min']) * 5)

            elif cinfo['type'] == ORDINAL:
                feature.append(col)

            else:
                if cinfo['size'] <= 2:
                    feature.append(col)
                else:
                    tmp = [0] * cinfo['size']
                    tmp[int(col)] = 1
                    feature += tmp
        features.append(feature)
        labels.append(label)

    return features, labels


DATASET_MODELS_MAP = {
    'mnist12': [
        (DecisionTreeClassifier(max_depth=30, class_weight='balanced'),
            "Decision Tree (max_depth=30)"),
        (LogisticRegression(
            solver='lbfgs', n_jobs=2, multi_class="auto", class_weight='balanced', max_iter=50),
            "Logistic Regression"),
        (MLPClassifier((100, ), max_iter=50), "MLP (100)")
    ],
    'mnist28': [
        (DecisionTreeClassifier(max_depth=30, class_weight='balanced'),
            "Decision Tree (max_depth=30)"),
        (LogisticRegression(
            solver='lbfgs', n_jobs=2, multi_class="auto", class_weight='balanced', max_iter=50),
            "Logistic Regression"),
        (MLPClassifier((100, ), max_iter=50), "MLP (100)")
    ],
    'adult': [
        (DecisionTreeClassifier(max_depth=15, class_weight='balanced'),
            "Decision Tree (max_depth=20)"),
        (AdaBoostClassifier(), "Adaboost (estimator=50)"),
        (LogisticRegression(
            solver='lbfgs', n_jobs=2, class_weight='balanced', max_iter=50),
            "Logistic Regression"),
        (MLPClassifier((50, ), max_iter=50), "MLP (50)")
    ],
    'census': [
        (DecisionTreeClassifier(max_depth=30, class_weight='balanced'),
            "Decision Tree (max_depth=30)"),
        (AdaBoostClassifier(), "Adaboost (estimator=50)"),
        (MLPClassifier((100, ), max_iter=50), "MLP (100)"),
    ],
    'credit': [
        (DecisionTreeClassifier(max_depth=30, class_weight='balanced'),
            "Decision Tree (max_depth=30)"),
        (AdaBoostClassifier(), "Adaboost (estimator=50)"),
        (MLPClassifier((100, ), max_iter=50), "MLP (100)"),
    ],
    'intrusion': [
        (DecisionTreeClassifier(max_depth=30, class_weight='balanced'),
            "Decision Tree (max_depth=30)"),
        (MLPClassifier((100, ), max_iter=50), "MLP (100)"),
    ],
    'covtype': [
        (DecisionTreeClassifier(max_depth=30, class_weight='balanced'),
            "Decision Tree (max_depth=30)"),
        (MLPClassifier((100, ), max_iter=50), "MLP (100)"),
    ],
    'news': [
        (LinearRegression(), "Linear Regression"),
        (MLPRegressor((100, ), max_iter=50), "MLP (100)")
    ]
}


def get_models(dataset):
    models = DATASET_MODELS_MAP.get(dataset)
    if models:
        return models

    else:
        raise ValueError('Could not find models for dataset {}'.format(dataset))


def default_gmm_likelihood(trainset, testset, n):
    gmm = GaussianMixture(n, covariance_type='diag')
    gmm.fit(testset)
    l1 = gmm.score(trainset)

    gmm.fit(trainset)
    l2 = gmm.score(testset)

    return [{
        "name": "default",
        "syn_likelihood": l1,
        "test_likelihood": l2,
    }]


def mapper(data, meta):
    data_t = []
    for row in data:
        row_t = []
        for id_, info in enumerate(meta):
            row_t.append(info['i2s'][int(row[id_])])
        data_t.append(row_t)
    return data_t


def default_bayesian_likelihood(dataset, trainset, testset, meta):
    struct = glob.glob("data/*/{}_structure.json".format(dataset))
    assert len(struct) == 1
    bn1 = BayesianNetwork.from_json(struct[0])

    trainset_mapped = mapper(trainset, meta)
    testset_mapped = mapper(testset, meta)
    prob = []
    for item in trainset_mapped:
        try:
            prob.append(bn1.probability(item))
        except Exception:
            prob.append(1e-8)

    l1 = np.mean(np.log(np.asarray(prob) + 1e-8))

    bn2 = BayesianNetwork.from_structure(trainset_mapped, bn1.structure)
    prob = []

    for item in testset_mapped:
        try:
            prob.append(bn2.probability(item))
        except Exception:
            prob.append(1e-8)

    l2 = np.mean(np.log(np.asarray(prob) + 1e-8))

    return [{
        "name": "default",
        "syn_likelihood": l1,
        "test_likelihood": l2,
    }]


DATASET_EVALUATOR_MAP = {
    "mnist12": default_multi_classification,
    "mnist28": default_multi_classification,
    "covtype": default_multi_classification,
    "intrusion": default_multi_classification,
    'credit': default_binary_classification,
    'census': default_binary_classification,
    'adult': default_binary_classification,
    'news': news_regression,
    'grid': default_gmm_likelihood,
    'gridr': default_gmm_likelihood,
    'ring': default_gmm_likelihood,
    'asia': default_bayesian_likelihood,
    'alarm': default_bayesian_likelihood,
    'child': default_bayesian_likelihood,
    'insurance': default_bayesian_likelihood,
}


def evalute_dataset(dataset, trainset, testset, meta):

    evaluator = DATASET_EVALUATOR_MAP.get(dataset)

    if evaluator is None:
        logging.warning("{} evaluation not defined.".format(dataset))
        return

    if dataset in ['asia', 'alarm', 'child', 'insurance']:
        return evaluator(dataset, trainset, testset, meta)

    if dataset in [
            "mnist12", "mnist28", "covtype", "intrusion", 'credit', 'census', 'adult', 'news']:
        x_train, y_train = make_features(trainset, meta)
        x_test, y_test = make_features(testset, meta)
        return evaluator(x_train, y_train, x_test, y_test, get_models(dataset))

    bayesian_parameter = BAYESIAN_PARAMETER.get(dataset)
    if bayesian_parameter:
        return evaluator(trainset, testset, bayesian_parameter)


def compute_distance(trainset, syn, meta, sample=300):
    mask_d = np.zeros(len(meta))

    for id_, info in enumerate(meta):
        if info['type'] in [CATEGORICAL, ORDINAL]:
            mask_d[id_] = 1
        else:
            mask_d[id_] = 0

    std = np.std(trainset, axis=0) + 1e-6

    dis_all = []
    for i in range(sample):
        current = syn[i]
        distance_d = (trainset - current) * mask_d > 0
        distance_d = np.sum(distance_d, axis=1)

        distance_c = (trainset - current) * (1 - mask_d) / 2 / std
        distance_c = np.sum(distance_c ** 2, axis=1)
        distance = np.sqrt(np.min(distance_c + distance_d))
        dis_all.append(distance)

    return np.mean(dis_all)


def get_arg_parser():
    parser = argparse.ArgumentParser(description='Evaluate output of one synthesizer.')
    parser.add_argument('--result', type=str, default='output/__result__', help='result dir')
    parser.add_argument(
        '--force', dest='force', action='store_true', help='overwrite result', default=False)
    parser.add_argument('synthetic', type=str, help='synthetic data folder')

    return parser


def main(result, synthetic, force):

    if not os.path.exists(args.result):
        os.makedirs(args.result)

    result_file = "{}/{}.json".format(args.result,
                                      args.synthetic.replace('/', '\t').split()[-1])
    if os.path.exists(result_file):
        logging.warning("result file {} exists.".format(result_file))
        if args.force:
            logging.warning("overwrite {}.".format(result_file))
        else:
            exit()

    logging.info("use result file {}.".format(result_file))

    synthetic_folder = args.synthetic
    synthetic_files = glob.glob("{}/*.npz".format(synthetic_folder))

    results = []

    for synthetic_file in synthetic_files:
        # synthetic_file is like xxx/xxx/dataset_iter_step.npz
        # iter is the iteration of experiment
        # step is the learning steps of some synthesizer, 0 if no learning
        syn = np.load(synthetic_file)['syn']
        if np.any(np.isnan(syn)):
            continue

        dataset_iter_step = synthetic_file.split('/')[-1]
        assert dataset_iter_step[-4:] == '.npz'
        dataset_iter_step = dataset_iter_step[:-4].split('_')

        dataset = dataset_iter_step[0]
        iter = int(dataset_iter_step[1])
        step = int(dataset_iter_step[2])

        data_filename = glob.glob("data/*/{}.npz".format(dataset))
        meta_filename = glob.glob("data/*/{}.json".format(dataset))

        if len(data_filename) != 1:
            logging.warning("Skip. Can't find dataset {}.".format(dataset))
            continue

        if len(meta_filename) != 1:
            logging.warning("Skip. Can't find meta {}.".format(dataset))
            continue

        data = np.load(data_filename[0])['test']
        data_train = np.load(data_filename[0])['train']
        with open(meta_filename[0]) as f:
            meta = json.load(f)

        logging.info("Evaluating {}".format(synthetic_file))
        performance = evalute_dataset(dataset, syn, data, meta)

        distance = compute_distance(data_train, syn, meta)
        res = {
            "dataset": dataset,
            "iter": iter,
            "step": step,
            "performance": performance,
            "distance": distance
        }

        results.append(res)

    with open(result_file, "w") as f:
        json.dump(results, f, sort_keys=True, indent=4, separators=(',', ': '))


if __name__ == "__main__":
    parser = get_arg_parser()
    args = parser.parse_args()
    main(*args)
