import pickle
import random

with open(f'./complex_graphs.pkl', 'rb') as f:
            subgraphs = pickle.load(f)

random.shuffle(subgraphs)

split = int(len(subgraphs) * 0.3)

# 分割成两个集合
sft_test = subgraphs[:split]   # 约占30%
sft_train = subgraphs[split:]   # 约占70%

with open("./Complex_Test.pkl", 'wb') as f:
            pickle.dump(sft_test, f)
            
with open("./Complex_Train.pkl", 'wb') as f:
            pickle.dump(sft_train, f)
