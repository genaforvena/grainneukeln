if conda env list | grep -q grain; then
	conda activate grain
else
	./install.sh
fi

python main.py assets/test_audio.wav output/
