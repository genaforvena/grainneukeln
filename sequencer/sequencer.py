import pydub.playback as playback

class SequencerController:

    def __init__(self):
        self.tempo = 160
        self.current_sample = 1
        self.sample_paths = {
            1: "",
            2: "",
            3: "",
            4: "",
            5: "",
            6: "",
            7: "",
            8: "",
        }
        self.sequences = {
            1: "",
            2: "",
            3: "",
            4: "",
            5: "",
            6: "",
            7: "",
            8: "",
        }
        self.playables = {
            1: None,
            2: None,
            3: None,
            4: None,
            5: None,
            6: None,
            7: None,
            8: None,
        }

    def __gen_playables(self, sample_number, sequence_number):
        from pydub import AudioSegment

        # Load a random audio file
        audio = AudioSegment.from_file(self.sample_paths[sample_number])

        # Set the length of each note in milliseconds
        note_length = 1000

        # Set the number of notes in the sequence
        num_notes = 10

        # Create an empty AudioSegment for the sequence
        sequence = AudioSegment.silent(duration=num_notes * note_length)

        # Check if the sequence is empty
        if self.sequences[sequence_number] == "":
            self.sequences[sequence_number] = "0" * num_notes
        # Add notes to the sequence based on the binary sequence
        for i, bit in enumerate(self.sequences[sequence_number] * (num_notes // 8)):
            if bit == '1':
                start = i * note_length
                end = start + note_length
                note = audio[start:end].fade_in(10).fade_out(10)
                sequence = sequence.overlay(note)

        self.playables[sample_number] = sequence

    def command(self, command = "help"):
        working = True
        while working:
            command = input(">>>")
            if command == "play":
                self.play_sequence()
            elif command == "stop":
                self.stop_sequence()
            elif command == "info":
                self.print_info()
            elif command.startswith("tempo"):
                self.set_tempo(command)
            elif command.startswith("sam"):
                self.set_sample(command)
            elif command.startswith("seq"):
                self.set_sequence(command)
            elif command == "help":
                self.print_help()
            elif command == "exit":
                working = False
                self.exit()
            else:
                print("Unknown command")

    def print_help(self):
        print("play - play the sequence")
        print("stop - stop the sequence")
        print("info - print the info")
        print("tempo - set the tempo")
        print("sample - set the sample")
        print("exit - exit the program")

    def print_info(self):
        print("Tempo: " + str(self.tempo))
        print("Sample paths: " + str(self.sample_paths))
        print("Sequence: " + str(self.sequences))

    def set_sample(self, command):
        if len(command.split(" ")) > 1:
            sample_number = int(command.split(" ")[1])
            if len(command.split(" ")) > 2:
                sample_path = command.split(" ")[2]
                self.sample_paths[sample_number] = sample_path
                self.__gen_playables(sample_number, sample_number)
            else:
                print("Unknown command")
        else:
            print("Unknown command")

    def set_sequence(self, command):
        if len(command.split(" ")) > 1:
            sequence_number = int(command.split(" ")[1])
            if len(command.split(" ")) > 2:
                sequence = command.split(" ")[2]
                self.sequences[sequence_number] = sequence
                self.__gen_playables(sequence_number, sequence_number)
            else:
                print("Unknown command")
        else:
            print("Unknown command")

    def set_tempo(self, command):
        if len(command.split(" ")) > 2:
            self.tempo = int(command.split(" ")[1])
        else:
            print("Unknown command")

    def play_sequence(self):
        # play the sequences in the order of the samples
        for sample_number in self.sample_paths:
            if self.playables[sample_number] is not None:
                playback.play(self.playables[sample_number])

    def stop_sequence(self):
        pass

    def exit(self):
        print("Exiting the sequencer")
