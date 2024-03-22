if conda env list | grep -q grain; then
	./install.sh
fi

conda activate grain
python main.py assets/test_audio.wav output/
