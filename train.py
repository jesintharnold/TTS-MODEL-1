from model import TransformerTTS
import torch
import torch.nn as nn
import os
import json
import matplotlib.pyplot as plt
from dataset import LJSpeechDataset,melspectogram_max_min
from torch.utils.data import DataLoader
import numpy as np
from torch.nn.utils.rnn import pad_sequence


best_val_loss = 100000000000

class TTStrain:
    def __init__(self,model,device,train_loader,val_loader,lr=1e-4):
        self.model=model.to(device)
        self.train_data=train_loader
        self.val_data=val_loader
        self.device=device
        self.duration_loss=nn.MSELoss()
        self.optimizer=torch.optim.Adam(self.model.parameters(),lr=lr)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, step_size=10, gamma=0.5)
        self.latest_checkpoint = None
        self.train_losses = []
        self.val_losses = []

    def train_epoch(self):
        total_loss=0.0
        for batch_idx,batch in enumerate(self.train_data):
            text = batch["phonemes"].to(self.device)
            spectogram = batch["mel"].to(self.device)
            durations = batch["duration"].to(self.device)
            self.optimizer.zero_grad()
            predicted_spectrogram, predicted_durations = self.model(text, spectogram, durations)

            if batch_idx == 0:
                print(f"Predicted durations (first sample): {predicted_durations[0].cpu().detach().numpy()}")
                print(f"Ground truth durations (first sample): {durations[0].cpu().numpy()}")
            
            spectogram_loss = 0.5 * nn.MSELoss()(predicted_spectrogram, spectogram) + 0.5 * nn.L1Loss()(predicted_spectrogram, spectogram)
            duration_loss = self.duration_loss(predicted_durations,durations)
            
            loss = spectogram_loss+2.0*duration_loss
            loss.backward()
            self.optimizer.step()
            self.scheduler.step()
            total_loss+=loss.item()
            if (batch_idx + 1) % 10 == 0:
                print(f"Batch {batch_idx + 1}/{len(self.train_data)}, Loss: {loss.item()}")
        return total_loss / len(self.train_data)
    
    def validate(self):
        self.model.eval()
        total_loss = 0.0
        with torch.no_grad():
            for batch in self.val_data:
                text = batch["phonemes"].to(self.device)
                spectogram = batch["mel"].to(self.device)
                durations = batch["duration"].to(self.device)
                predicted_spectrogram, predicted_durations = self.model(text, spectogram, durations)
                spectrogram_loss = 0.5 * nn.MSELoss()(predicted_spectrogram, spectogram) + 0.5 * nn.L1Loss()(predicted_spectrogram, spectogram)
                duration_loss = self.duration_loss(predicted_durations, durations)
                loss = spectrogram_loss + 2.0*duration_loss
                total_loss += loss.item()
        return total_loss / len(self.val_data)

    def save_checkpoint(self, epoch, save_dir="checkpoints"):
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        if self.latest_checkpoint is not None:
            try:
                os.remove(self.latest_checkpoint)
                print(f"Removed previous checkpoint: {self.latest_checkpoint}")
            except Exception as e:
                print(f"Error removing checkpoint {self.latest_checkpoint}: {e}")
    
        checkpoint_path = os.path.join(save_dir, f"model_epoch_{epoch}.pt")
        torch.save({
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict()
        }, checkpoint_path)
        print(f"Checkpoint saved at {checkpoint_path}")
        self.latest_checkpoint = checkpoint_path

    def plot_losses(self, save_dir="checkpoints"):
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        plt.figure(figsize=(10, 6))
        plt.plot(self.train_losses, label='Training Loss')
        plt.plot(self.val_losses, label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Losses')
        plt.legend()
        plt.grid(True)
        plot_path = os.path.join(save_dir, 'loss_plot.png')
        plt.savefig(plot_path)
        plt.close()
        print(f"Loss plot saved at {plot_path}")

    def train(self, epoch=10, save_dir="checkpoints", patience=20):
        best_val_loss = float('inf')
        patience_counter = 0
        for i in range(epoch):
            train_loss = self.train_epoch()
            val_loss = self.validate()
            self.train_losses.append(train_loss)
            self.val_losses.append(val_loss)
            print(f"Epoch - {i}, Train loss - {train_loss}, Val loss - {val_loss}")
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                self.save_checkpoint(i, save_dir)
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    print(f"Early stopping at epoch {i} due to no improvement in validation loss.")
                    break
            self.plot_losses(save_dir)
            
        







metadata_train_path="./LJSPEECH/train.txt"
metadata_val_path="./LJSPEECH/val.txt"
mel_dir="./LJSPEECH/mel"
duration_dir="./LJSPEECH/duration"

def create_phonemes_dict():
   phonemes=set()
   with open(metadata_train_path,'r',encoding='utf-8') as file:
        for line in file:
            _phonemes_=line.strip().split("|")[2].strip('{}')
            for phoneme in _phonemes_.split():
                phonemes.add(phoneme)
   arr=sorted(phonemes)
   phoneme_map={ val:key for key,val in enumerate(arr)}
   phoneme_map["PAD"] = len(arr)
   phoneme_map["UNK"] = len(arr)+1
   return phoneme_map

phoneme_map=create_phonemes_dict()   
def collatefn(batch):
    mels = []
    durations = []
    phonemes = []
    texts = []
    for item in batch:
        mels.append(item['mel'])
        durations.append(item['duration'])
        phonemes.append(item['phonemes'])
        texts.append(item['text'])
    mels_padded = pad_sequence(mels, batch_first=True, padding_value=0)
    durations_padded = pad_sequence(durations, batch_first=True, padding_value=0)
    phonemes_padded = pad_sequence(phonemes, batch_first=True, padding_value=phoneme_map["PAD"])
    return {
        'mel': mels_padded,
        'duration': durations_padded,
        'phonemes': phonemes_padded,
        'text': texts
    }

if __name__ == "__main__":
    
    vocab_size = len(phoneme_map)
    embedding_dim = 768
    hidden_dim = 768
    n_heads = 12
    n_layers = 12
    batch_size = 16
    num_epochs = 200
    train_max_data=10000
    val_max_data=1000
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Training the data in device - ",device)

    model = TransformerTTS(vocab_size=vocab_size,embedding_dim=embedding_dim,hidden_dim=hidden_dim,n_heads=n_heads,n_layers=n_layers,output_dim=80)
    optimizer= torch.optim.Adam(model.parameters(),lr=1e-4)

    with open("./mel_min_max.json",'r') as f:
        melconfig = json.load(f)
        mel_min=melconfig["mel_min"]
        mel_max=melconfig["mel_max"]


    train_dataset=LJSpeechDataset(metadata_path=metadata_train_path,mel_dir=mel_dir,duration_dir=duration_dir,phoneme_dict=phoneme_map,max_data=train_max_data,mel_min=mel_min,mel_max=mel_max)
    train_loader=DataLoader(
        dataset=train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=4,
        collate_fn=collatefn
    )


    for batch in train_dataset:
        print(batch)
        break


    val_dataset=LJSpeechDataset(metadata_path=metadata_val_path,mel_dir=mel_dir,duration_dir=duration_dir,phoneme_dict=phoneme_map,max_data=val_max_data,mel_min=mel_min,mel_max=mel_max)
    val_loader=DataLoader(
        dataset=val_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=4,
        collate_fn=collatefn
    )
    trainer = TTStrain(model=model,device=device,train_loader=train_loader,val_loader=val_loader,lr=1e-4)
    trainer.train(epoch=num_epochs)
    